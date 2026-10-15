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


def calculate_finance(
    revenues: np.ndarray,
    samples: pd.DataFrame,
    rent_rates: np.ndarray,
    salary: float,
    regime: str,
    taxes: Mapping[str, object],
) -> FinanceResult:
    if not np.isfinite(revenues).all() or (revenues < 0).any():
        raise ValueError("Выручка должна быть конечной и неотрицательной")
    if not np.isfinite(salary) or salary < 0:
        raise ValueError("Зарплата должна быть конечной и неотрицательной")
    if not np.isfinite(rent_rates).all() or (rent_rates <= 0).any():
        raise ValueError("Ставки аренды должны быть положительными и конечными")
    contribution_rate = float(taxes["employer_contributions_rate"]["value"])
    rent = samples["area_m2"].to_numpy()[:, None] * rent_rates[None, :]
    base_payroll = samples["staff_count"].to_numpy()[:, None] * salary
    contributions = base_payroll * contribution_rate
    payroll = np.broadcast_to(base_payroll + contributions, revenues.shape)
    cogs = revenues * samples["cogs_share_of_revenue"].to_numpy()[:, None]
    other = np.broadcast_to(samples["other_opex_rub"].to_numpy()[:, None], revenues.shape)
    expenses = rent + payroll + cogs + other
    tax = monthly_tax(revenues, expenses, contributions, regime, taxes)
    total = expenses + tax
    capex = np.broadcast_to(samples["capex_rub"].to_numpy()[:, None], revenues.shape)
    return FinanceResult(rent, payroll, cogs, tax, other, total, revenues - total, capex)
