from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

from geostart.model.demand import DEFAULT_RUNS, DEFAULT_SEED

MONTHS_PER_YEAR = 12
INCOME_TAX_REDUCTION_LIMIT = 0.5
MINIMUM_EXPENSES_TAX_RATE = 0.01
MEDIUM_RISK_THRESHOLD = 0.2
HIGH_RISK_THRESHOLD = 0.5
COST_PARAMETERS = ("area_m2", "staff_count", "cogs_share_of_revenue", "other_opex_rub")


class TaxRegime(StrEnum):
    INCOME = "usn_income_6"
    INCOME_MINUS_EXPENSES = "usn_income_minus_expenses_15"


class Risk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def employee_contributions(salary: float, taxes: Mapping[str, object], niche: str) -> float:
    if not np.isfinite(salary) or salary < 0:
        raise ValueError("Зарплата должна быть конечной и неотрицательной")
    rules = taxes.get("social_contributions_employer")
    if not rules:
        return salary * float(taxes["employer_contributions_rate"]["value"])
    standard = rules["standard_rate"]
    injury = rules["injury_rate_min"]
    standard_rate = float(standard["value"]) if niche in standard["applies_to"] else 0.0
    injury_rate = float(injury["value"]) if niche in injury["applies_to"] else 0.0
    threshold = rules["msp_threshold_1_5_mrot"]
    reduced = rules["msp_reduced_rate_above_1_5_mrot"]
    if niche in threshold["applies_to"] and niche in reduced["applies_to"]:
        below = min(salary, float(threshold["value"]))
        unified = below * standard_rate + (salary - below) * float(reduced["value"])
    else:
        unified = salary * standard_rate
    return unified + salary * injury_rate


@dataclass(frozen=True)
class VatBand:
    lower: float
    upper: float
    rate: float
    source: str | None


def vat_band(taxes: Mapping[str, object], niche: str) -> VatBand | None:
    rules = taxes.get("vat_on_usn")
    if not rules:
        return None
    names = ("exemption_revenue_threshold", "special_rate_tier1_max_revenue", "special_rate_tier1")
    if any(niche not in rules[name]["applies_to"] for name in names):
        return None
    lower, upper, rate = (float(rules[name]["value"]) for name in names)
    if not np.isfinite([lower, upper, rate]).all() or lower < 0 or upper <= lower or not 0 <= rate <= 1:
        raise ValueError("Проверьте пороги и специальную ставку НДС в исследовании")
    return VatBand(lower, upper, rate, rules["special_rate_tier1"].get("source"))


def monthly_vat(revenues: np.ndarray, taxes: Mapping[str, object], niche: str) -> np.ndarray:
    band = vat_band(taxes, niche)
    if band is None:
        return np.zeros_like(revenues)
    annual = revenues * MONTHS_PER_YEAR
    applicable = (annual > band.lower) & (annual <= band.upper)
    return np.where(applicable, revenues * band.rate, 0.0)


def sample_finance_parameters(
    parameters: Mapping[str, object], runs: int = DEFAULT_RUNS, seed: int = DEFAULT_SEED
) -> pd.DataFrame:
    generator = np.random.default_rng(np.random.SeedSequence([seed, 1]))
    ranges = {name: parameters["costs"][name] for name in COST_PARAMETERS}
    ranges["capex_rub"] = parameters["capex_rub"]
    sampled = {}
    for name, bounds in ranges.items():
        lower, upper = float(bounds["p10"]), float(bounds["p90"])
        if not np.isfinite([lower, upper]).all() or lower < 0 or upper < lower:
            raise ValueError(f"Проверьте положительные границы параметра {name}")
        if name in ("area_m2", "capex_rub") and lower <= 0:
            raise ValueError(f"Параметр {name} должен быть положительным")
        if name == "cogs_share_of_revenue" and upper > 1:
            raise ValueError("Доля себестоимости должна быть от 0 до 1")
        sampled[name] = generator.uniform(lower, upper, runs)
    return pd.DataFrame(sampled)


def monthly_tax(
    revenue: np.ndarray,
    expenses: np.ndarray,
    contributions: np.ndarray,
    regime: str,
    taxes: Mapping[str, object],
) -> np.ndarray:
    try:
        selected = TaxRegime(regime)
    except ValueError as error:
        raise ValueError("Неизвестный режим налога, выберите УСН с доходов или с разницы") from error
    if selected == TaxRegime.INCOME:
        gross_tax = revenue * float(taxes["usn_income_rate"]["value"])
        return gross_tax - np.minimum(contributions, gross_tax * INCOME_TAX_REDUCTION_LIMIT)
    tax = np.maximum(revenue - expenses, 0) * float(taxes["usn_income_minus_expenses_rate"]["value"])
    return np.maximum(tax, revenue * MINIMUM_EXPENSES_TAX_RATE)


def risk_levels(profits: np.ndarray) -> np.ndarray:
    loss_share = np.mean(profits < 0, axis=0)
    return np.where(
        loss_share > HIGH_RISK_THRESHOLD,
        Risk.HIGH,
        np.where(loss_share >= MEDIUM_RISK_THRESHOLD, Risk.MEDIUM, Risk.LOW),
    )


def payback_months(capex: np.ndarray, profits: np.ndarray) -> np.ndarray:
    result = np.full(np.broadcast_shapes(capex.shape, profits.shape), np.nan)
    return np.divide(capex, profits, out=result, where=profits > 0)


@dataclass(frozen=True)
class FinanceResult:
    rent: np.ndarray
    payroll: np.ndarray
    cogs: np.ndarray
    taxes: np.ndarray
    other: np.ndarray
    total: np.ndarray
    profits: np.ndarray
    capex: np.ndarray
    contributions: np.ndarray
    usn_taxes: np.ndarray
    vat: np.ndarray


def calculate_finance(
    revenues: np.ndarray,
    samples: pd.DataFrame,
    rent_rates: np.ndarray,
    salary: float,
    regime: str,
    taxes: Mapping[str, object],
    *,
    niche: str,
) -> FinanceResult:
    if not np.isfinite(revenues).all() or (revenues < 0).any():
        raise ValueError("Выручка должна быть конечной и неотрицательной")
    if not np.isfinite(salary) or salary < 0:
        raise ValueError("Зарплата должна быть конечной и неотрицательной")
    if not np.isfinite(rent_rates).all() or (rent_rates <= 0).any():
        raise ValueError("Ставки аренды должны быть положительными и конечными")
    rent = samples["area_m2"].to_numpy()[:, None] * rent_rates[None, :]
    base_payroll = samples["staff_count"].to_numpy()[:, None] * salary
    contributions = np.broadcast_to(
        samples["staff_count"].to_numpy()[:, None] * employee_contributions(salary, taxes, niche),
        revenues.shape,
    )
    payroll = np.broadcast_to(base_payroll + contributions, revenues.shape)
    cogs = revenues * samples["cogs_share_of_revenue"].to_numpy()[:, None]
    other = np.broadcast_to(samples["other_opex_rub"].to_numpy()[:, None], revenues.shape)
    expenses = rent + payroll + cogs + other
    usn_tax = monthly_tax(revenues, expenses, contributions, regime, taxes)
    vat = monthly_vat(revenues, taxes, niche)
    tax = usn_tax + vat
    total = expenses + tax
    capex = np.broadcast_to(samples["capex_rub"].to_numpy()[:, None], revenues.shape)
    return FinanceResult(
        rent, payroll, cogs, tax, other, total, revenues - total, capex, contributions, usn_tax, vat
    )
