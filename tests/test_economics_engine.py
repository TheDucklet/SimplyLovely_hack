import numpy as np
import pytest
import yaml

from geostart.economics.credit import (
    LoanTerms,
    Schedule,
    annual_dscr,
    get_product,
    loan_schedule,
    max_loan,
    monthly_dscr,
)
from geostart.economics.engine import (
    PlanSettings,
    ScenarioInputs,
    break_even_revenue,
    evaluate,
    project,
    project_npv,
    steady_year,
)
from geostart.economics.norms import load_norms
from geostart.economics.sampling import optional_summary, quantile_samples, summary
from geostart.economics.taxes import (
    LegalForm,
    Regime,
    ausn_active,
    block_taxes,
    owner_contributions,
    patent_cost,
    tax_rules,
    vat_rates,
)
from geostart.settings import research_dir

RUNS = 4


@pytest.fixture(scope="module")
def taxes() -> dict:
    with (research_dir() / "taxes" / "2026.yaml").open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def flat_inputs(revenue: float = 900_000.0, capex: float = 2_000_000.0) -> ScenarioInputs:
    ones = np.ones(RUNS)
    return ScenarioInputs(
        revenue_steady=ones * revenue,
        area_m2=ones * 40,
        rent_rate=ones * 1000,
        staff=ones * 4,
        cogs_share=ones * 0.3,
        other_opex=ones * 50_000,
        capex=ones * capex,
        deposit=ones * 40_000,
        working_capital=ones * 100_000,
        franchise_fee=np.zeros(RUNS),
        salary=60_000.0,
    )


def flat_settings(taxes: dict, regime: Regime = Regime.USN_INCOME, **changes: object) -> PlanSettings:
    values = {
        "horizon": 36,
        "start_month": 1,
        "ramp": (1.0,),
        "seasonality": (1.0,) * 12,
        "revenue_growth": 0.0,
        "rent_growth": 0.0,
        "wage_growth": 0.0,
        "opex_growth": 0.0,
        "discount_rate": 0.0,
        "regime": regime,
        "legal_form": LegalForm.IP,
        "loan_amount": np.zeros(RUNS),
        "loan_terms": LoanTerms(0.19, 36, Schedule.ANNUITY),
        "dscr_threshold": 1.25,
        "rules": tax_rules(taxes, "coffee"),
        "taxes": taxes,
        "start_year": 2026,
        "patent_annual": None,
    }
    values.update(changes)
    return PlanSettings(**values)


def test_annuity_matches_reference_payment() -> None:
    interest, principal = loan_schedule(np.array([1_000_000.0]), LoanTerms(0.12, 36, Schedule.ANNUITY), 48)
    payments = interest + principal
    assert payments[0, 0] == pytest.approx(33_214.31, abs=0.01)
    assert np.allclose(payments[0, :36], payments[0, 0])
    assert principal.sum() == pytest.approx(1_000_000.0)
    assert np.all(payments[0, 36:] == 0)


def test_differentiated_schedule_repays_evenly() -> None:
    interest, principal = loan_schedule(
        np.array([1_200_000.0]), LoanTerms(0.12, 12, Schedule.DIFFERENTIATED), 12
    )
    assert np.allclose(principal, 100_000.0)
    assert interest[0, 0] == pytest.approx(12_000.0)
    assert np.all(np.diff(interest[0]) < 0)


def test_zero_rate_loan_has_no_interest() -> None:
    interest, principal = loan_schedule(np.array([120_000.0]), LoanTerms(0.0, 12, Schedule.ANNUITY), 12)
    assert interest.sum() == 0
    assert np.allclose(principal, 10_000.0)


def test_max_loan_hits_dscr_threshold() -> None:
    terms = LoanTerms(0.19, 36, Schedule.ANNUITY)
    annual_cash = np.array([1_500_000.0])
    limit = max_loan(annual_cash, terms, 1.25)
    interest, principal = loan_schedule(limit, terms, 36)
    _, minimum = annual_dscr(np.full((1, 36), annual_cash[0] / 12), interest + principal, 36)
    assert minimum[0] == pytest.approx(1.25)


def test_quantile_samples_keep_reference_points() -> None:
    values = quantile_samples("выручки", 100.0, 200.0, 400.0, 1000, np.random.default_rng(1))
    p10, p50, p90 = summary(values)
    assert p10 == pytest.approx(100.0, rel=0.02)
    assert p50 == pytest.approx(200.0, rel=0.02)
    assert p90 == pytest.approx(400.0, rel=0.02)
    assert values.min() >= 0


def test_quantile_samples_reject_wrong_order() -> None:
    with pytest.raises(ValueError, match="p10 ≤ p50 ≤ p90"):
        quantile_samples("выручки", 3.0, 2.0, 1.0, 10, np.random.default_rng(1))


def test_optional_summary_puts_missing_values_on_chosen_side() -> None:
    values = np.array([1.0, 2.0, np.nan, np.nan, np.nan])
    assert optional_summary(values)[1] is None
    assert optional_summary(values, missing_high=False)[2] == pytest.approx(1.6)


def test_owner_contributions_follow_threshold_and_cap(taxes: dict) -> None:
    rules = tax_rules(taxes, "coffee")
    revenue = np.array([200_000.0, 1_300_000.0, 1e10])
    result = owner_contributions(rules, revenue, 12)
    assert result[0] == pytest.approx(rules.owner_fixed_annual)
    assert result[1] == pytest.approx(rules.owner_fixed_annual + 10_000.0)
    assert result[2] == pytest.approx(rules.owner_fixed_annual + rules.owner_extra_cap)
    assert owner_contributions(rules, revenue[:1], 6)[0] == pytest.approx(rules.owner_fixed_annual / 2)


def test_vat_rates_follow_revenue_bands(taxes: dict) -> None:
    rules = tax_rules(taxes, "coffee")
    rates = vat_rates(rules, np.array([19e6, 25e6, 300e6, 500e6]))
    assert list(rates) == [0.0, 0.05, 0.07, 0.22]


def test_income_tax_reduction_is_limited_to_half(taxes: dict) -> None:
    rules = tax_rules(taxes, "coffee")
    revenue = np.array([12e6])
    result = block_taxes(
        rules,
        Regime.USN_INCOME,
        LegalForm.IP,
        revenue,
        np.zeros(1),
        np.array([5e6]),
        np.array([4.0]),
        12,
        np.zeros(1),
        None,
    )
    assert result.main[0] == pytest.approx(12e6 * 0.06 / 2)


def test_profit_regime_uses_minimum_tax_and_carries_loss(taxes: dict) -> None:
    rules = tax_rules(taxes, "coffee")
    revenue = np.array([6e6])
    first = block_taxes(
        rules,
        Regime.USN_PROFIT,
        LegalForm.OOO,
        revenue,
        np.array([7e6]),
        np.zeros(1),
        np.array([4.0]),
        12,
        np.zeros(1),
        None,
    )
    assert first.main[0] == pytest.approx(6e6 * 0.01)
    assert first.loss_carry[0] == pytest.approx(1e6)
    second = block_taxes(
        rules,
        Regime.USN_PROFIT,
        LegalForm.OOO,
        revenue,
        np.array([4e6]),
        np.zeros(1),
        np.array([4.0]),
        12,
        first.loss_carry,
        None,
    )
    assert second.main[0] == pytest.approx((2e6 - 1e6) * 0.15)
    assert second.loss_carry[0] == pytest.approx(0.0)


def test_patent_falls_back_to_income_regime_above_limit(taxes: dict) -> None:
    rules = tax_rules(taxes, "coffee")
    cost = patent_cost(taxes, "tula", "coffee", np.array([40.0, 40.0]), 0.6, None)
    assert cost is not None
    result = block_taxes(
        rules,
        Regime.PATENT,
        LegalForm.IP,
        np.array([10e6, 30e6]),
        np.zeros(2),
        np.zeros(2),
        np.array([4.0, 4.0]),
        12,
        np.zeros(2),
        cost.annual,
    )
    assert list(result.fallback) == [False, True]
    assert result.vat[0] == 0
    assert result.vat[1] == pytest.approx(30e6 * 0.05)


def test_patent_is_not_available_for_companies(taxes: dict) -> None:
    rules = tax_rules(taxes, "coffee")
    with pytest.raises(ValueError, match="только ИП"):
        block_taxes(
            rules,
            Regime.PATENT,
            LegalForm.OOO,
            np.ones(1),
            np.zeros(1),
            np.zeros(1),
            np.ones(1),
            12,
            np.zeros(1),
            np.ones(1),
        )


def test_moscow_patent_uses_central_rate_when_district_is_unknown(taxes: dict) -> None:
    unknown = patent_cost(taxes, "moscow", "coffee", np.ones(1), 0.6, None)
    outside = patent_cost(taxes, "moscow", "coffee", np.ones(1), 0.6, False)
    assert unknown is not None and outside is not None
    assert unknown.annual[0] > outside.annual[0]
    assert patent_cost(taxes, "tula", "pickup_point", np.ones(1), 0.0, None) is None


def test_patent_cost_reads_generic_city_keys(taxes: dict) -> None:
    saint_petersburg = patent_cost(taxes, "saint_petersburg", "coffee", np.ones(2), 0.6, None)
    tula = patent_cost(taxes, "tula", "bakery", np.ones(2), 0.6, None)
    assert saint_petersburg is not None
    assert tula is not None
    assert np.all(saint_petersburg.annual > 0)
    assert np.all(tula.annual > 0)


def test_flat_projection_payback_and_npv(taxes: dict) -> None:
    inputs = flat_inputs()
    settings = flat_settings(taxes)
    projection = project(inputs, settings)
    monthly_cash = projection.operating_cash[0, 0]
    assert np.allclose(projection.operating_cash, monthly_cash)
    metrics = evaluate(inputs, settings, projection)
    assert metrics.payback_months[0] == pytest.approx(inputs.investment[0] / monthly_cash)
    expected_npv = monthly_cash * 36 + 140_000 - inputs.investment[0]
    assert metrics.npv[0] == pytest.approx(expected_npv)
    assert project_npv(projection, (1 + metrics.irr_annual) ** (1 / 12) - 1)[0] == pytest.approx(0.0, abs=1.0)


def test_payback_is_missing_when_cash_never_covers_investment(taxes: dict) -> None:
    inputs = flat_inputs(revenue=300_000.0)
    settings = flat_settings(taxes)
    metrics = evaluate(inputs, settings, project(inputs, settings))
    assert np.isnan(metrics.payback_months).all()
    assert np.isnan(metrics.irr_annual).all()
    assert metrics.probability_no_payback == 1.0
    assert metrics.probability_loss == 1.0


def test_break_even_gives_zero_profit(taxes: dict) -> None:
    inputs = flat_inputs()
    for regime in (Regime.USN_INCOME, Regime.USN_PROFIT):
        settings = flat_settings(taxes, regime)
        point = break_even_revenue(inputs, settings)
        profit = steady_year(inputs, settings, point)["profit"]
        assert np.allclose(profit, 0.0, atol=1.0)
        assert (point < inputs.revenue_steady).all()


def test_ramp_and_growth_change_revenue_path(taxes: dict) -> None:
    inputs = flat_inputs()
    settings = flat_settings(taxes, ramp=(0.5, 0.75), revenue_growth=0.1)
    revenue = project(inputs, settings).revenue[0]
    assert revenue[0] == pytest.approx(450_000.0)
    assert revenue[1] == pytest.approx(675_000.0)
    assert revenue[2] == pytest.approx(900_000.0)
    assert revenue[12] == pytest.approx(990_000.0)


def test_loan_changes_owner_cash_but_not_project_cash(taxes: dict) -> None:
    inputs = flat_inputs()
    without = project(inputs, flat_settings(taxes, regime=Regime.USN_INCOME))
    with_loan = project(
        inputs, flat_settings(taxes, regime=Regime.USN_INCOME, loan_amount=np.full(RUNS, 1_000_000.0))
    )
    assert np.allclose(without.operating_cash, with_loan.operating_cash)
    assert with_loan.cumulative_owner_cash[0, 0] > without.cumulative_owner_cash[0, 0]
    assert with_loan.principal.sum(axis=1) == pytest.approx(np.full(RUNS, 1_000_000.0))


def test_loan_is_limited_by_investment(taxes: dict) -> None:
    inputs = flat_inputs()
    projection = project(inputs, flat_settings(taxes, loan_amount=np.full(RUNS, 1e9)))
    assert np.allclose(projection.loan, inputs.investment)


def test_norms_have_sources_or_explicit_gaps() -> None:
    norms = load_norms()
    assert norms.discount_rate() == pytest.approx(0.2)
    for niche in ("coffee", "pickup_point"):
        items = norms.niche(niche).items
        assert len(items["seasonality"].value) == 12
        assert all(norm.note for norm in items.values())
    with pytest.raises(ValueError, match="нет нормативов"):
        norms.niche("dentistry")


def test_grace_period_pays_interest_only() -> None:
    interest, principal = loan_schedule(
        np.array([1_000_000.0]), LoanTerms(0.12, 36, Schedule.ANNUITY, grace_months=6), 40
    )
    assert np.allclose(interest[0, :6], 10_000.0)
    assert np.all(principal[0, :6] == 0)
    assert principal.sum() == pytest.approx(1_000_000.0)
    assert np.all(principal[0, 36:] == 0)


def test_grace_must_be_shorter_than_term() -> None:
    with pytest.raises(ValueError, match="Льготный период"):
        LoanTerms(0.12, 12, Schedule.ANNUITY, grace_months=12)


def test_monthly_dscr_skips_months_without_payments() -> None:
    ratios = monthly_dscr(np.array([[100.0, 100.0]]), np.array([[50.0, 0.0]]))
    assert ratios[0, 0] == pytest.approx(2.0)
    assert np.isinf(ratios[0, 1])


def test_vtb_product_has_sourced_rate() -> None:
    product = get_product("vtb_express")
    assert product.rate_annual.value == pytest.approx(0.26)
    assert product.rate_annual.source
    assert product.min_business_age_months.value == 12
    with pytest.raises(ValueError, match="не найден"):
        get_product("unknown")


def test_ausn_applies_within_limits_and_dates(taxes: dict) -> None:
    rules = tax_rules(taxes, "coffee", "tula")
    staff = np.array([4.0, 4.0, 6.0])
    revenue = np.array([10e6, 70e6, 10e6])
    active = ausn_active(rules, Regime.AUSN_INCOME, 2026, revenue, 12, staff)
    assert list(active) == [True, False, False]
    assert not ausn_active(rules, Regime.AUSN_INCOME, 2028, revenue, 12, staff).any()
    assert not ausn_active(rules, Regime.USN_INCOME, 2026, revenue, 12, staff).any()
    assert tax_rules(taxes, "coffee", "kazan").ausn.region_start is None


def test_ausn_income_tax_has_no_reduction_and_no_vat(taxes: dict) -> None:
    rules = tax_rules(taxes, "coffee", "tula")
    revenue = np.array([30e6])
    active = np.array([True])
    result = block_taxes(
        rules,
        Regime.AUSN_INCOME,
        LegalForm.IP,
        revenue,
        np.zeros(1),
        np.zeros(1),
        np.array([4.0]),
        12,
        np.zeros(1),
        None,
        active,
    )
    assert result.main[0] == pytest.approx(30e6 * 0.08)
    assert result.owner[0] == 0
    assert result.vat[0] == 0


def test_ausn_profit_uses_three_percent_minimum(taxes: dict) -> None:
    rules = tax_rules(taxes, "coffee", "tula")
    result = block_taxes(
        rules,
        Regime.AUSN_PROFIT,
        LegalForm.OOO,
        np.array([10e6]),
        np.array([9.9e6]),
        np.zeros(1),
        np.array([4.0]),
        12,
        np.zeros(1),
        None,
        np.array([True]),
    )
    assert result.main[0] == pytest.approx(10e6 * 0.03)


def test_ausn_removes_employer_contributions(taxes: dict) -> None:
    inputs = flat_inputs()
    rules = tax_rules(taxes, "coffee", "tula")
    usn = project(inputs, flat_settings(taxes, Regime.USN_INCOME, rules=rules, horizon=24))
    ausn = project(inputs, flat_settings(taxes, Regime.AUSN_INCOME, rules=rules, horizon=24))
    assert usn.contributions[0, 0] > 1000
    assert ausn.contributions[0, 0] == pytest.approx(2959 / 12)
    assert not ausn.fallback.any()
    assert not ausn.ausn_ended


def test_ausn_after_experiment_returns_contributions(taxes: dict) -> None:
    inputs = flat_inputs()
    settings = flat_settings(
        taxes, Regime.AUSN_INCOME, rules=tax_rules(taxes, "coffee", "tula"), horizon=36, start_year=2027
    )
    projection = project(inputs, settings)
    assert projection.ausn_ended
    assert projection.contributions[0, 0] == pytest.approx(2959 / 12)
    assert projection.contributions[0, 12] > 1000
    assert not projection.fallback.any()


def test_depreciation_follows_asset_lives(taxes: dict) -> None:
    inputs = flat_inputs(capex=1_200_000.0)
    settings = flat_settings(taxes, capex_lives=((0.5, 12), (0.5, 24)))
    depreciation = project(inputs, settings).depreciation[0]
    assert depreciation[0] == pytest.approx(600_000 / 12 + 600_000 / 24)
    assert depreciation[12] == pytest.approx(600_000 / 24)
    assert depreciation[24] == 0
    assert depreciation.sum() == pytest.approx(1_200_000.0)


def test_first_profit_month_follows_ramp(taxes: dict) -> None:
    inputs = flat_inputs()
    settings = flat_settings(taxes, ramp=(0.2, 0.4, 0.6, 1.0))
    metrics = evaluate(inputs, settings, project(inputs, settings))
    projection = project(inputs, settings)
    first = int(metrics.first_profit_month[0])
    assert projection.net_profit[0, first - 1] > 0
    assert (projection.net_profit[0, : first - 1] <= 0).all()


def test_months_sum_to_year_totals(taxes: dict) -> None:
    inputs = flat_inputs()
    settings = flat_settings(taxes, start_month=7, ramp=(0.5, 0.8), revenue_growth=0.065)
    projection = project(inputs, settings)
    yearly = projection.taxes.reshape(RUNS, 3, 12).sum(axis=2).sum(axis=1)
    assert yearly == pytest.approx(projection.taxes.sum(axis=1))
    assert projection.revenue[:, :12].sum(axis=1) + projection.revenue[:, 12:].sum(axis=1) == pytest.approx(
        projection.revenue.sum(axis=1)
    )
