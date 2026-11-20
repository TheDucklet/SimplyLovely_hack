import numpy as np

from geostart.economics.sampling import optional_summary
from geostart.economics.service import Adjustments, Calculation, calculate, calculation_versions
from geostart.schemas_v2 import (
    SensitivityFactor,
    SensitivityFactorCode,
    SensitivityMetrics,
    SensitivityPoint,
    SensitivityReport,
    SensitivityRequest,
    SensitivityStress,
    SensitivityStressCode,
    SensitivitySummary,
)

PAYBACK_LIMIT_MONTHS = 24
REVENUE_STRESS_MULTIPLIER = 0.8
RENT_STRESS_MULTIPLIER = 1.15
LOAN_RATE_STRESS_ADD = 0.03
FACTORS: tuple[tuple[SensitivityFactorCode, str], ...] = (
    ("revenue", "Выручка"),
    ("rent", "Аренда"),
    ("wages", "Зарплаты"),
    ("cogs_share", "Себестоимость"),
    ("capex", "Вложения"),
)
STRESSES: tuple[tuple[SensitivityStressCode, str, Adjustments], ...] = (
    ("revenue_minus_20", "Выручка ниже на 20%", Adjustments(revenue=REVENUE_STRESS_MULTIPLIER)),
    ("rent_plus_15", "Аренда выше на 15%", Adjustments(rent=RENT_STRESS_MULTIPLIER)),
    ("rate_plus_3", "Ставка кредита выше на 3 пункта", Adjustments(loan_rate_add=LOAN_RATE_STRESS_ADD)),
    (
        "combined",
        "Все три сразу",
        Adjustments(
            revenue=REVENUE_STRESS_MULTIPLIER,
            rent=RENT_STRESS_MULTIPLIER,
            loan_rate_add=LOAN_RATE_STRESS_ADD,
        ),
    ),
)


def median_payback(months: np.ndarray) -> float | None:
    repaid = months[np.isfinite(months)]
    if repaid.size and repaid.size * 2 == months.size:
        return float(repaid.max())
    return optional_summary(months)[1]


def scenario_metrics(calc: Calculation) -> SensitivityMetrics:
    return SensitivityMetrics(
        profit_steady_month_p50=float(np.median(calc.metrics.steady["profit"])),
        npv_p50=float(np.median(calc.metrics.npv)),
        payback_months_p50=median_payback(calc.metrics.payback_months),
    )


def scenario_summary(calc: Calculation) -> SensitivitySummary:
    months = calc.metrics.payback_months
    return SensitivitySummary(
        **scenario_metrics(calc).model_dump(),
        probability_no_payback_24=float(np.mean(~np.isfinite(months) | (months > PAYBACK_LIMIT_MONTHS))),
    )


def factor_point(
    request: SensitivityRequest, base: Calculation, code: SensitivityFactorCode, change: float
) -> SensitivityPoint:
    calc = calculate(request, adjustments=Adjustments(**{code: 1.0 + change}), demand=base.demand)
    return SensitivityPoint(**scenario_metrics(calc).model_dump(), change=change)


def profit_spread(factor: SensitivityFactor) -> float:
    return abs(factor.high.profit_steady_month_p50 - factor.low.profit_steady_month_p50)


def evaluate_sensitivity(request: SensitivityRequest) -> SensitivityReport:
    base = calculate(request)
    shift = request.shift_share
    factors = [
        SensitivityFactor(
            code=code,
            name=name,
            low=factor_point(request, base, code, -shift),
            high=factor_point(request, base, code, shift),
        )
        for code, name in FACTORS
    ]
    stresses = [
        SensitivityStress(
            code=code,
            name=name,
            **scenario_summary(calculate(request, adjustments=adjustments, demand=base.demand)).model_dump(),
        )
        for code, name, adjustments in STRESSES
    ]
    return SensitivityReport(
        versions=calculation_versions(base.context),
        shift_share=shift,
        base=scenario_summary(base),
        factors=sorted(factors, key=profit_spread, reverse=True),
        stresses=stresses,
    )
