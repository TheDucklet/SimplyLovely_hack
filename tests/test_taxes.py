from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
import yaml

from geostart import settings
from geostart.model.finance import calculate_finance, employee_contributions, monthly_vat


@pytest.fixture
def tax_research() -> dict:
    return yaml.safe_load((settings.research_dir() / "taxes/2026.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("salary", "coffee", "pickup"),
    [
        (0, 0, 0),
        (30_000, 9060, 9060),
        (40_639.5, 12_273.129, 12_273.129),
        (42_500, 12_555.925, 12_835),
        (65_000, 15_975.925, 19_630),
        (90_000, 19_775.925, 27_180),
    ],
)
def test_contributions_apply_threshold_to_one_employee(
    tax_research: dict, salary: float, coffee: float, pickup: float
) -> None:
    assert employee_contributions(salary, tax_research, "coffee") == pytest.approx(coffee)
    assert employee_contributions(salary, tax_research, "pickup_point") == pytest.approx(pickup)


def test_contribution_rates_honor_niche_applicability(tax_research: dict) -> None:
    taxes = deepcopy(tax_research)
    taxes["social_contributions_employer"]["msp_reduced_rate_above_1_5_mrot"]["applies_to"] = []
    assert employee_contributions(65_000, taxes, "coffee") == pytest.approx(19_630)
    taxes = deepcopy(tax_research)
    taxes["social_contributions_employer"]["injury_rate_min"]["applies_to"] = []
    assert employee_contributions(65_000, taxes, "coffee") == pytest.approx(15_845.925)


@pytest.mark.parametrize("niche", ["coffee", "pickup_point"])
def test_vat_boundaries_and_unsupported_revenue(tax_research: dict, niche: str) -> None:
    annual = np.array([0, 20_000_000 - 1, 20_000_000, 20_000_000 + 1, 272_500_000, 272_500_000 + 1])
    revenues = annual / 12
    expected = np.array([0, 0, 0, revenues[3] * 0.05, revenues[4] * 0.05, 0])
    np.testing.assert_allclose(monthly_vat(revenues, tax_research, niche), expected)


def test_vat_honors_niche_applicability(tax_research: dict) -> None:
    tax_research["vat_on_usn"]["special_rate_tier1"]["applies_to"] = ["coffee"]
    revenues = np.array([2_000_000.0])
    assert monthly_vat(revenues, tax_research, "coffee")[0] == 100_000
    assert monthly_vat(revenues, tax_research, "pickup_point")[0] == 0


@pytest.mark.parametrize("regime", ["usn_income_6", "usn_income_minus_expenses_15"])
def test_finance_adds_vat_without_deducting_contributions_from_it(tax_research: dict, regime: str) -> None:
    revenues = np.array([[2_000_000.0], [1_000_000.0]])
    samples = pd.DataFrame(
        {
            "area_m2": [40, 40],
            "staff_count": [2.5, 2.5],
            "cogs_share_of_revenue": [0.3, 0.3],
            "other_opex_rub": [60_000, 60_000],
            "capex_rub": [3_000_000, 3_000_000],
        }
    )
    result = calculate_finance(
        revenues, samples, np.array([7000]), 65_000, regime, tax_research, niche="coffee"
    )
    np.testing.assert_allclose(result.contributions, 2.5 * 15_975.925)
    np.testing.assert_allclose(result.payroll, 2.5 * (65_000 + 15_975.925))
    np.testing.assert_array_equal(result.vat[:, 0], [100_000, 0])
    np.testing.assert_array_equal(result.taxes, result.usn_taxes + result.vat)
    np.testing.assert_array_equal(
        result.total, result.rent + result.payroll + result.cogs + result.other + result.taxes
    )
    np.testing.assert_array_equal(result.profits, revenues - result.total)
    if regime == "usn_income_6":
        np.testing.assert_allclose(result.usn_taxes[:, 0], [80_060.1875, 30_000])


def test_invalid_vat_band_is_rejected(tax_research: dict) -> None:
    tax_research["vat_on_usn"]["special_rate_tier1_max_revenue"]["value"] = 1
    with pytest.raises(ValueError, match="Проверьте пороги"):
        monthly_vat(np.array([2_000_000]), tax_research, "coffee")
