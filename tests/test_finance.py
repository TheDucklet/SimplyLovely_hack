import numpy as np
import pandas as pd
import pytest

from geostart.model.finance import calculate_finance, monthly_tax, payback_months, risk_levels

TAXES = {
    "usn_income_rate": {"value": 0.06},
    "usn_income_minus_expenses_rate": {"value": 0.15},
    "employer_contributions_rate": {"value": 0.30},
}


def test_income_tax_reduction_is_capped_at_half() -> None:
    revenue = np.array([1_000_000.0, 1_000_000.0])
    tax = monthly_tax(revenue, np.zeros(2), np.array([40_000.0, 1000.0]), "usn_income_6", TAXES)
    np.testing.assert_array_equal(tax, [30_000, 59_000])


def test_expenses_tax_has_annual_minimum_for_constant_month() -> None:
    tax = monthly_tax(
        np.full(3, 1_000_000.0),
        np.array([900_000, 990_000, 1_200_000]),
        np.zeros(3),
        "usn_income_minus_expenses_15",
        TAXES,
    )
    np.testing.assert_array_equal(tax, [15_000, 10_000, 10_000])


def test_finance_costs_include_payroll_contributions() -> None:
    samples = pd.DataFrame(
        {
            "area_m2": [40.0],
            "staff_count": [4.0],
            "cogs_share_of_revenue": [0.3],
            "other_opex_rub": [60_000.0],
            "capex_rub": [3_000_000.0],
        }
    )
    result = calculate_finance(
        np.array([[1_000_000.0]]), samples, np.array([7000.0]), 50_000, "usn_income_6", TAXES
    )
    assert result.rent[0, 0] == 280_000
    assert result.payroll[0, 0] == 260_000
    assert result.cogs[0, 0] == 300_000
    assert result.taxes[0, 0] == 30_000
    assert result.total[0, 0] == 930_000
    assert result.profits[0, 0] == 70_000


def test_risk_threshold_boundaries_and_zero_profit() -> None:
    profits = np.ones((10, 4))
    profits[:2, 1] = -1
    profits[:5, 2] = -1
    profits[:6, 3] = -1
    np.testing.assert_array_equal(risk_levels(profits), ["low", "medium", "medium", "high"])
    assert risk_levels(np.zeros((3, 1)))[0] == "low"


def test_payback_is_missing_for_zero_and_negative_profit() -> None:
    result = payback_months(np.array([3_000_000.0] * 3), np.array([100_000, 0, -100_000]))
    assert result[0] == 30
    assert np.isnan(result[1:]).all()


def test_unknown_tax_regime_is_rejected() -> None:
    with pytest.raises(ValueError, match="Неизвестный режим"):
        monthly_tax(np.array([1.0]), np.array([0.0]), np.array([0.0]), "unknown", TAXES)
