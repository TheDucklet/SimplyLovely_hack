from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import yaml

from geostart import settings
from geostart.config import get_city, get_niche
from geostart.economics.credit import LoanTerms, Schedule
from geostart.economics.engine import (
    MODEL_VERSION,
    Metrics,
    PlanSettings,
    Projection,
    ScenarioInputs,
    evaluate,
    first_year_taxes,
    project,
    total_taxes,
)
from geostart.economics.norms import MONTHS_PER_YEAR, Norm, Norms, load_norms, norms_path
from geostart.economics.sampling import bounds_samples, optional_summary, quantile_samples, summary
from geostart.economics.taxes import (
    MOSCOW,
    REGIME_NAMES,
    LegalForm,
    PatentCost,
    Regime,
    patent_cost,
    tax_rules,
)
from geostart.model.demand import DEFAULT_RUNS, DEFAULT_SEED
from geostart.model.finance import HIGH_RISK_THRESHOLD, MEDIUM_RISK_THRESHOLD
from geostart.research import city_parameters
from geostart.schemas import Assumption, MoneyRange
from geostart.schemas_v2 import (
    CashBand,
    CreditCheckReport,
    CreditCheckRequest,
    CreditSummary,
    DemandSummary,
    EconomicsMetrics,
    EconomicsReport,
    EconomicsRequest,
    Financing,
    GeoDemand,
    InvestmentSummary,
    MonthRow,
    NormsResponse,
    NormValue,
    OptionalRange,
    ParameterValue,
    PlanCheck,
    RegimeOption,
    RevenueDemand,
    SteadyMonth,
    TaxSummary,
    TrafficDemand,
    Versions,
    YearRow,
)

COST_SEED_STREAM = 2
DEMAND_SEED_STREAM = 3
DAYS_PER_MONTH = 30.4
CENTRAL_OKRUG = "ЦАО"
UNKNOWN_DATA_VERSION = "нет данных"
TRUDVSEM_SOURCE = "https://opendata.trudvsem.ru"
CONFIRMED_DSCR_PROBABILITY = 0.8
REJECTED_DSCR_PROBABILITY = 0.5
REJECTED_FLAGS = 2
PERCENT = 100.0
COST_PARAMETERS = {
    "area_m2": ("Площадь помещения", "м²"),
    "staff_count": ("Число сотрудников", "чел."),
    "cogs_share_of_revenue": ("Доля себестоимости", "доля выручки"),
    "other_opex_rub": ("Прочие расходы", "₽/месяц"),
    "capex_rub": ("Вложения в открытие", "₽"),
}
UNIT_LABELS = {
    "share_year": "доля в год",
    "months": "мес.",
    "ratio": "раз",
    "months_of_rent": "мес. аренды",
    "months_of_cogs": "мес. себестоимости",
    "share": "доля",
    "share_of_steady_revenue": "доля плановой выручки",
    "multiplier_by_calendar_month": "множитель",
}
CALCULATION_LIMITS = (
    "НДС считается по выручке календарного года без перехода на ставку внутри года. "
    "Налог на прибыль и дивиденды ООО не моделируются. "
    "Стоимость бизнеса в конце горизонта не учитывается, возвращаются только залог и оборотный запас."
)


@dataclass(frozen=True)
class EconomicContext:
    city: str
    niche: str
    parameters: Mapping[str, object]
    taxes: Mapping[str, object]
    rents: pd.DataFrame
    salary: float | None
    data_version: str
    norms: Norms


def context_revision(city: str, niche: str) -> tuple:
    root = settings.research_dir()
    paths = (
        root / "niche_params" / f"{niche}.yaml",
        root / "taxes" / "2026.yaml",
        root / "rent" / f"{city}.csv",
        settings.processed_dir(city) / "wages.parquet",
        norms_path(),
    )
    return tuple((str(path), path.stat().st_mtime_ns) for path in paths if path.is_file())


def load_context(city: str, niche: str) -> EconomicContext:
    get_city(city)
    get_niche(niche)
    return cached_context(city, niche, context_revision(city, niche))


@lru_cache(maxsize=16)
def cached_context(city: str, niche: str, revision: tuple) -> EconomicContext:
    root = settings.research_dir()
    with (root / "niche_params" / f"{niche}.yaml").open(encoding="utf-8") as stream:
        parameters = city_parameters(yaml.safe_load(stream), city)
    with (root / "taxes" / "2026.yaml").open(encoding="utf-8") as stream:
        taxes = yaml.safe_load(stream)
    rent_path = root / "rent" / f"{city}.csv"
    if not rent_path.is_file():
        raise FileNotFoundError(f"Нет ставок аренды города {city}, добавьте research/rent/{city}.csv")
    salary, version = city_salary(settings.processed_dir(city) / "wages.parquet", parameters)
    return EconomicContext(
        city, niche, parameters, taxes, pd.read_csv(rent_path), salary, version, load_norms()
    )


def city_salary(path: Path, parameters: Mapping[str, object]) -> tuple[float | None, str]:
    if not path.is_file():
        return None, UNKNOWN_DATA_VERSION
    wages = pd.read_parquet(path)
    selected = wages.loc[wages["profession"].eq(parameters["costs"]["wage_profession"]), "salary_p50"]
    version = (
        pd.to_datetime(wages["collected_at"]).max().date().isoformat()
        if not wages.empty
        else UNKNOWN_DATA_VERSION
    )
    return (float(selected.median()) if not selected.empty else None), version


def city_rent(rents: pd.DataFrame) -> float:
    values = pd.to_numeric(rents["rent_rub_m2_month_p50"], errors="coerce")
    values = values.loc[values.notna() & values.gt(0)]
    if values.empty:
        raise ValueError("Нет положительных ставок аренды, загрузите ставки города")
    return float(values.median())


def generator(stream: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([DEFAULT_SEED, stream]))


@dataclass(frozen=True)
class DemandSamples:
    revenue: np.ndarray
    source: str
    provider: str | None = None
    h3: str | None = None
    district: str | None = None
    rent_rate: float | None = None
    central: bool | None = None
    assumptions: list[Assumption] = field(default_factory=list)


def unit_value(context: EconomicContext) -> float:
    parameter = context.norms.niche(context.niche).unit_value_parameter
    return float(context.parameters["demand"][parameter]["p50"])


def geo_demand(context: EconomicContext, demand: GeoDemand) -> DemandSamples:
    from geostart.model.service import (
        cached_location,
        city_context,
        input_revision,
        load_inputs,
        rent_rates,
        validate_location,
    )
    from geostart.model.simulation import simulate_revenues

    inputs = load_inputs(context.city, context.niche)
    validate_location(inputs, demand.lat, demand.lon, context.city)
    cell = h3.latlng_to_cell(demand.lat, demand.lon, get_city(context.city).h3_resolution)
    samples = city_context(context.city, context.niche).samples
    features, index, model = cached_location(
        context.city, context.niche, input_revision(context.city, context.niche), cell
    )
    revenue = simulate_revenues(model, samples, index)[:, 0]
    row = features.iloc[[index]]
    district = str(row.district.iloc[0])
    central = None
    if context.city == MOSCOW:
        okrug = inputs.district_okrugs.get(district)
        central = None if okrug is None else okrug == CENTRAL_OKRUG
    note = Assumption(
        name="Источник выручки",
        value="Модель Хаффа ГеоСтарт по открытым данным, 200 сценариев параметров спроса",
        unit="",
        source="https://www.openstreetmap.org",
    )
    return DemandSamples(
        revenue, "geostart", None, cell, district, float(rent_rates(inputs, row)[0]), central, [note]
    )


def estimate_demand(demand: RevenueDemand, runs: int) -> DemandSamples:
    bounds = demand.revenue_month
    revenue = quantile_samples(
        "выручки", bounds.p10, bounds.p50, bounds.p90, runs, generator(DEMAND_SEED_STREAM)
    )
    label = demand.provider or "оценка пользователя"
    note = Assumption(name="Источник выручки", value=f"Внешняя оценка, {label}", unit="", source=None)
    return DemandSamples(revenue, "revenue", demand.provider, assumptions=[note])


def traffic_demand(context: EconomicContext, demand: TrafficDemand, runs: int) -> DemandSamples:
    random = generator(DEMAND_SEED_STREAM)
    visitors = demand.visitors_per_day
    conversion = demand.conversion
    if demand.avg_check_rub is None:
        parameter = context.norms.niche(context.niche).unit_value_parameter
        check = context.parameters["demand"][parameter]
        check_samples = bounds_samples("среднего чека", check, runs, random)
    else:
        bounds = demand.avg_check_rub
        check_samples = quantile_samples("среднего чека", bounds.p10, bounds.p50, bounds.p90, runs, random)
    revenue = (
        quantile_samples("трафика", visitors.p10, visitors.p50, visitors.p90, runs, random)
        * quantile_samples("конверсии", conversion.p10, conversion.p50, conversion.p90, runs, random)
        * check_samples
        * DAYS_PER_MONTH
    )
    label = demand.provider or "оценка пользователя"
    note = Assumption(
        name="Источник выручки",
        value=f"Трафик × конверсия × средний чек × {DAYS_PER_MONTH:g} дня, {label}",
        unit="",
        source=None,
    )
    return DemandSamples(revenue, "traffic", demand.provider, assumptions=[note])


def resolve_demand(context: EconomicContext, request: EconomicsRequest) -> DemandSamples:
    demand = request.demand
    if isinstance(demand, GeoDemand):
        return geo_demand(context, demand)
    if isinstance(demand, RevenueDemand):
        return estimate_demand(demand, DEFAULT_RUNS)
    return traffic_demand(context, demand, DEFAULT_RUNS)


def cost_samples(context: EconomicContext, request: EconomicsRequest, runs: int) -> dict[str, np.ndarray]:
    random = generator(COST_SEED_STREAM)
    costs = context.parameters["costs"]
    sampled = {
        name: bounds_samples(
            name, context.parameters["capex_rub"] if name == "capex_rub" else costs[name], runs, random
        )
        for name in COST_PARAMETERS
    }
    overrides = {
        "area_m2": request.premises.area_m2,
        "staff_count": request.operations.staff_count,
        "cogs_share_of_revenue": request.operations.cogs_share,
        "other_opex_rub": request.operations.other_opex_rub_month,
        "capex_rub": request.investment.capex_rub,
    }
    for name, value in overrides.items():
        if value is not None:
            sampled[name] = np.full(runs, float(value))
    sampled["cogs_share_of_revenue"] = np.minimum(sampled["cogs_share_of_revenue"], 0.99)
    return sampled


@dataclass(frozen=True)
class Calculation:
    context: EconomicContext
    request: EconomicsRequest
    demand: DemandSamples
    inputs: ScenarioInputs
    settings: PlanSettings
    projection: Projection
    metrics: Metrics
    options: list[RegimeOption]
    patent: PatentCost | None
    chosen_automatically: bool
    rent_rate: float
    rent_source: str | None
    salary_source: str | None
    unit_value: float
    warnings: list[str]


def loan_terms(context: EconomicContext, financing: Financing | None) -> LoanTerms:
    norms = context.norms
    rate = (
        financing.rate_annual
        if financing and financing.rate_annual is not None
        else norms.value("loan_rate_annual")
    )
    term = (
        financing.term_months
        if financing and financing.term_months is not None
        else int(norms.value("loan_term_months"))
    )
    schedule = Schedule(financing.schedule) if financing else Schedule.ANNUITY
    return LoanTerms(rate, term, schedule)


def loan_amount(financing: Financing | None, investment: np.ndarray) -> np.ndarray:
    if financing is None:
        return np.zeros_like(investment)
    if financing.loan_amount_rub is not None:
        return np.full_like(investment, financing.loan_amount_rub)
    if financing.loan_share is not None:
        return investment * financing.loan_share
    return np.zeros_like(investment)


def regime_eligibility(
    regime: Regime, legal_form: LegalForm, patent: PatentCost | None, staff: np.ndarray, staff_limit: float
) -> str | None:
    if regime != Regime.PATENT:
        return None
    if legal_form != LegalForm.IP:
        return "Патент доступен только ИП"
    if patent is None:
        return "Стоимость патента для ниши и города не исследована"
    if float(np.median(staff)) > staff_limit:
        return f"Штат больше {staff_limit:g} человек"
    return None


def default_start_month() -> int:
    return date.today().month % MONTHS_PER_YEAR + 1


def calculate(request: EconomicsRequest) -> Calculation:
    city = get_city(request.city).code
    niche = get_niche(request.niche).code
    context = load_context(city, niche)
    norms = context.norms
    niche_norms = norms.niche(niche)
    demand = resolve_demand(context, request)
    runs = len(demand.revenue)
    costs = cost_samples(context, request, runs)
    warnings: list[str] = []
    if request.premises.rent_rub_m2_month is not None:
        rent_rate, rent_source = request.premises.rent_rub_m2_month, None
    elif demand.rent_rate is not None:
        rent_rate, rent_source = demand.rent_rate, rent_reference(context.rents, demand.district)
    else:
        rent_rate, rent_source = city_rent(context.rents), rent_reference(context.rents, None)
    salary = request.operations.salary_rub_month or context.salary
    if salary is None:
        raise ValueError(
            f"Нет данных о зарплатах города {city}, "
            "укажите зарплату сотрудника в поле operations.salary_rub_month"
        )
    salary_source = None if request.operations.salary_rub_month else TRUDVSEM_SOURCE
    deposit_months = (
        request.premises.security_deposit_months
        if request.premises.security_deposit_months is not None
        else niche_norms.value("security_deposit_months")
    )
    area = costs["area_m2"]
    cogs_share = costs["cogs_share_of_revenue"]
    working_capital = (
        np.full(runs, request.investment.working_capital_rub)
        if request.investment.working_capital_rub is not None
        else niche_norms.value("working_capital_cogs_months") * demand.revenue * cogs_share
    )
    inputs = ScenarioInputs(
        revenue_steady=demand.revenue,
        area_m2=area,
        rent_rate=np.full(runs, float(rent_rate)),
        staff=costs["staff_count"],
        cogs_share=cogs_share,
        other_opex=costs["other_opex_rub"],
        capex=costs["capex_rub"],
        deposit=deposit_months * area * rent_rate,
        working_capital=working_capital,
        salary=float(salary),
    )
    rules = tax_rules(context.taxes, niche)
    central = (
        request.premises.central_district if request.premises.central_district is not None else demand.central
    )
    patent = patent_cost(context.taxes, city, niche, area, niche_norms.value("hall_share_of_area"), central)
    legal_form = LegalForm(request.tax.legal_form)
    terms = loan_terms(context, request.financing)
    loan = loan_amount(request.financing, inputs.investment)
    if (loan > inputs.investment).any():
        warnings.append("Сумма кредита больше вложений, в расчёте кредит ограничен суммой вложений")
    base = {
        "horizon": request.horizon_months,
        "start_month": request.start_month or default_start_month(),
        "ramp": niche_norms.series("ramp_up_share"),
        "seasonality": niche_norms.series("seasonality"),
        "revenue_growth": norms.value("inflation_annual"),
        "rent_growth": norms.value("rent_indexation_annual"),
        "wage_growth": norms.value("wage_growth_annual"),
        "opex_growth": norms.value("opex_indexation_annual"),
        "discount_rate": (
            request.discount_rate_annual
            if request.discount_rate_annual is not None
            else norms.discount_rate()
        ),
        "legal_form": legal_form,
        "loan_amount": loan,
        "loan_terms": terms,
        "dscr_threshold": norms.value("dscr_threshold"),
        "rules": rules,
        "taxes": context.taxes,
        "patent_annual": None if patent is None else patent.annual,
    }
    options: list[RegimeOption] = []
    projections: dict[Regime, tuple[PlanSettings, Projection]] = {}
    for regime in Regime:
        reason = regime_eligibility(regime, legal_form, patent, inputs.staff, rules.patent_staff_limit)
        if reason is None:
            plan = PlanSettings(regime=regime, **base)
            result = project(inputs, plan)
            projections[regime] = (plan, result)
            first, horizon = float(np.median(first_year_taxes(result))), float(np.median(total_taxes(result)))
        else:
            first = horizon = None
        options.append(
            RegimeOption(
                regime=regime.value,
                name=REGIME_NAMES[regime],
                eligible=reason is None,
                reason=reason,
                taxes_first_year_p50=first,
                taxes_horizon_p50=horizon,
            )
        )
    automatic = request.tax.regime == "auto"
    if automatic:
        chosen = min(projections, key=lambda item: float(np.median(total_taxes(projections[item][1]))))
    else:
        chosen = Regime(request.tax.regime)
        if chosen not in projections:
            reason = next(option.reason for option in options if option.regime == chosen.value)
            raise ValueError(f"Режим {REGIME_NAMES[chosen]} недоступен: {reason}")
    plan, result = projections[chosen]
    metrics = evaluate(inputs, plan, result)
    if result.patent_lost.any():
        warnings.append(
            f"В {result.patent_lost.mean() * PERCENT:.0f}% сценариев выручка или штат выше лимитов патента, "
            "для них налог посчитан по УСН «Доходы»"
        )
    if result.general_vat.any():
        warnings.append(
            f"В {result.general_vat.mean() * PERCENT:.0f}% сценариев выручка выше лимита УСН, "
            "НДС посчитан по общей ставке, а смена режима не моделируется"
        )
    if context.norms.niche(niche).items["seasonality"].source is None:
        warnings.append("Сезонность ниши не исследована, выручка распределена по месяцам равномерно")
    unit = (
        request.demand.avg_check_rub.p50
        if isinstance(request.demand, TrafficDemand) and request.demand.avg_check_rub is not None
        else unit_value(context)
    )
    return Calculation(
        context,
        request,
        demand,
        inputs,
        plan,
        result,
        metrics,
        options,
        patent,
        automatic,
        float(rent_rate),
        rent_source,
        salary_source,
        unit,
        warnings,
    )


def rent_reference(rents: pd.DataFrame, district: str | None) -> str | None:
    rows = rents.loc[rents["zone"].eq(district)] if district else rents
    sources = rows["source"].dropna()
    return str(sources.iloc[0]) if not sources.empty else None


def money(values: np.ndarray) -> MoneyRange:
    p10, p50, p90 = summary(values)
    return MoneyRange(p10=p10, p50=p50, p90=p90)


def optional(values: np.ndarray, *, missing_high: bool = True) -> OptionalRange:
    p10, p50, p90 = optional_summary(values, missing_high=missing_high)
    return OptionalRange(p10=p10, p50=p50, p90=p90)


def risk_level(probability_loss: float) -> str:
    if probability_loss > HIGH_RISK_THRESHOLD:
        return "high"
    if probability_loss >= MEDIUM_RISK_THRESHOLD:
        return "medium"
    return "low"


def norm_text(norm: Norm) -> float | str:
    if isinstance(norm.value, tuple):
        return ", ".join(f"{value:g}" for value in norm.value)
    return norm.value


def norm_assumptions(norms: Norms, niche: str) -> list[Assumption]:
    items = [*norms.common.values(), *norms.niche(niche).items.values()]
    return [
        Assumption(
            name=norm.name if norm.source else f"{norm.name} – допущение без источника",
            value=norm_text(norm),
            unit=UNIT_LABELS.get(norm.unit, norm.unit),
            source=norm.source,
        )
        for norm in items
    ]


def calculation_assumptions(calc: Calculation) -> list[Assumption]:
    context = calc.context
    request = calc.request
    result = list(calc.demand.assumptions)
    overrides = {
        "area_m2": request.premises.area_m2,
        "staff_count": request.operations.staff_count,
        "cogs_share_of_revenue": request.operations.cogs_share,
        "other_opex_rub": request.operations.other_opex_rub_month,
        "capex_rub": request.investment.capex_rub,
    }
    for code, (name, unit) in COST_PARAMETERS.items():
        bounds = context.parameters["capex_rub"] if code == "capex_rub" else context.parameters["costs"][code]
        if overrides[code] is not None:
            result.append(
                Assumption(name=f"{name} пользователя", value=float(overrides[code]), unit=unit, source=None)
            )
            continue
        result.append(
            Assumption(name=name, value=float(bounds["p50"]), unit=unit, source=bounds.get("source"))
        )
    result.append(
        Assumption(
            name="Зарплата сотрудника" if calc.salary_source else "Зарплата сотрудника пользователя",
            value=calc.inputs.salary,
            unit="₽/месяц",
            source=calc.salary_source,
        )
    )
    rent_name = "Ставка аренды пользователя" if request.premises.rent_rub_m2_month else "Ставка аренды"
    if calc.demand.district and not request.premises.rent_rub_m2_month:
        rent_name = f"Ставка аренды района {calc.demand.district}"
    elif calc.rent_source and not request.premises.rent_rub_m2_month:
        rent_name = "Ставка аренды по медиане города"
    result.append(
        Assumption(name=rent_name, value=calc.rent_rate, unit="₽/м² в месяц", source=calc.rent_source)
    )
    result.extend(norm_assumptions(context.norms, context.niche))
    regime = Regime(calc.settings.regime)
    result.append(
        Assumption(
            name="Налоговый режим",
            value=REGIME_NAMES[regime],
            unit="",
            source=calc.settings.rules.sources.get(regime),
        )
    )
    if calc.patent is not None:
        result.append(
            Assumption(
                name=calc.patent.description,
                value=float(np.median(calc.patent.annual)),
                unit="₽/год",
                source=calc.patent.source,
            )
        )
    if calc.settings.legal_form == LegalForm.IP:
        result.append(
            Assumption(
                name="Фиксированные взносы ИП за себя",
                value=calc.settings.rules.owner_fixed_annual,
                unit="₽/год",
                source=calc.settings.rules.sources.get("owner"),
            )
        )
    result.append(
        Assumption(name="Границы финансового расчёта", value=CALCULATION_LIMITS, unit="", source=None)
    )
    return result


def monthly_rows(calc: Calculation) -> list[MonthRow]:
    p = calc.projection
    r = calc.metrics.representative
    cumulative = p.cumulative_project_cash[r]
    start = calc.settings.start_month
    return [
        MonthRow(
            month=month + 1,
            calendar_month=(start - 1 + month) % MONTHS_PER_YEAR + 1,
            revenue=float(p.revenue[r, month]),
            cogs=float(p.cogs[r, month]),
            rent=float(p.rent[r, month]),
            payroll=float(p.wages[r, month] + p.contributions[r, month]),
            other=float(p.other[r, month]),
            taxes=float(p.taxes[r, month]),
            ebitda=float(p.ebitda[r, month]),
            interest=float(p.interest[r, month]),
            principal=float(p.principal[r, month]),
            net_profit=float(p.net_profit[r, month]),
            owner_cash_flow=float(p.owner_cash[r, month]),
            cumulative_project_cash=float(cumulative[month]),
        )
        for month in range(calc.settings.horizon)
    ]


def year_rows(calc: Calculation) -> list[YearRow]:
    p = calc.projection
    r = calc.metrics.representative
    rows = []
    for year in range(-(-calc.settings.horizon // MONTHS_PER_YEAR)):
        window = slice(year * MONTHS_PER_YEAR, (year + 1) * MONTHS_PER_YEAR)
        revenue = float(p.revenue[r, window].sum())
        ebitda = float(p.ebitda[r, window].sum())
        rows.append(
            YearRow(
                year=year + 1,
                revenue=revenue,
                operating_costs=revenue - ebitda,
                ebitda=ebitda,
                taxes=float(p.taxes[r, window].sum()),
                interest=float(p.interest[r, window].sum()),
                principal=float(p.principal[r, window].sum()),
                net_profit=float(p.net_profit[r, window].sum()),
                operating_cash_flow=float(p.operating_cash[r, window].sum()),
            )
        )
    return rows


def build_report(calc: Calculation) -> EconomicsReport:
    context = calc.context
    p = calc.projection
    m = calc.metrics
    r = m.representative
    steady = m.steady
    regime = Regime(calc.settings.regime)
    cumulative = p.cumulative_project_cash
    band = np.quantile(cumulative, (0.1, 0.5, 0.9), axis=0)
    margin = np.divide(
        steady["ebitda"],
        steady["revenue"],
        out=np.full(len(steady["revenue"]), np.nan),
        where=steady["revenue"] > 0,
    )
    cogs_p50 = float(np.median(calc.inputs.cogs_share))
    loan_active = bool((p.loan > 0).any())
    terms = calc.settings.loan_terms
    threshold = calc.settings.dscr_threshold
    return EconomicsReport(
        city=context.city,
        niche=context.niche,
        versions=Versions(
            model=MODEL_VERSION,
            norms=context.norms.version,
            data=context.data_version,
            taxes=str(context.taxes.get("updated", context.taxes.get("year"))),
        ),
        scenarios=calc.inputs.runs,
        horizon_months=calc.settings.horizon,
        start_month=calc.settings.start_month,
        discount_rate_annual=calc.settings.discount_rate,
        demand=DemandSummary(
            source=calc.demand.source,
            provider=calc.demand.provider,
            revenue_steady_month=money(calc.inputs.revenue_steady),
            h3=calc.demand.h3,
            district=calc.demand.district,
        ),
        tax=TaxSummary(
            regime=regime.value,
            name=REGIME_NAMES[regime],
            legal_form=calc.settings.legal_form.value,
            chosen_automatically=calc.chosen_automatically,
            options=calc.options,
        ),
        investment=InvestmentSummary(
            capex=float(np.median(calc.inputs.capex)),
            security_deposit=float(np.median(calc.inputs.deposit)),
            working_capital=float(np.median(calc.inputs.working_capital)),
            total=money(calc.inputs.investment),
            loan=float(np.median(p.loan)),
            own_funds=float(np.median(calc.inputs.investment - p.loan)),
        ),
        steady_month=SteadyMonth(
            revenue=float(steady["revenue"][r]),
            cogs=float(steady["cogs"][r]),
            rent=float(steady["rent"][r]),
            wages=float(steady["wages"][r]),
            payroll_contributions=float(steady["contributions"][r]),
            other=float(steady["other"][r]),
            ebitda=float(steady["ebitda"][r]),
            tax=float(steady["main_tax"][r]),
            owner_contributions=float(steady["owner_tax"][r]),
            vat=float(steady["vat"][r]),
            profit=float(steady["profit"][r]),
        ),
        metrics=EconomicsMetrics(
            npv=money(m.npv),
            irr_annual=optional(m.irr_annual, missing_high=False),
            payback_months=optional(m.payback_months),
            discounted_payback_months=optional(m.discounted_payback_months),
            probability_no_payback=m.probability_no_payback,
            probability_loss=m.probability_loss,
            risk_level=risk_level(m.probability_loss),
            profit_steady_month=money(steady["profit"]),
            ebitda_margin_p50=float(np.nanmedian(margin)) if np.isfinite(margin).any() else None,
            break_even_revenue_month=optional(m.break_even_revenue),
            break_even_units_per_day=optional(m.break_even_revenue / calc.unit_value / DAYS_PER_MONTH),
            safety_margin=optional(m.safety_margin, missing_high=False),
            unit_name=context.norms.niche(context.niche).unit_name,
            unit_value_rub=calc.unit_value,
            contribution_margin_per_unit=calc.unit_value * (1.0 - cogs_p50),
        ),
        credit=CreditSummary(
            amount=float(np.median(p.loan)),
            rate_annual=terms.rate_annual,
            term_months=terms.term_months,
            schedule=terms.schedule.value,
            first_payment=float(np.median(p.interest[:, 0] + p.principal[:, 0])),
            total_interest=float(np.median(p.interest.sum(axis=1))),
            dscr_first_year=optional(m.dscr_first_year),
            dscr_min=optional(m.dscr_min),
            dscr_threshold=threshold,
            probability_dscr_below_threshold=float(np.mean(m.dscr_min < threshold)) if loan_active else 0.0,
            max_loan_rub=money(m.max_loan),
        ),
        monthly=monthly_rows(calc),
        cash_band=[
            CashBand(
                month=month + 1,
                p10=float(band[0, month]),
                p50=float(band[1, month]),
                p90=float(band[2, month]),
            )
            for month in range(calc.settings.horizon)
        ],
        years=year_rows(calc),
        assumptions=calculation_assumptions(calc),
        warnings=calc.warnings,
    )


def evaluate_economics(request: EconomicsRequest) -> EconomicsReport:
    return build_report(calculate(request))


def percentile(samples: np.ndarray, value: float) -> float:
    filled = np.where(np.isfinite(samples), samples, np.inf)
    return float(np.mean(filled <= value) * PERCENT)


def plan_check(
    code: str, name: str, value: float, samples: np.ndarray, flag_when: str, unit: str
) -> PlanCheck:
    low, middle, high = optional_summary(samples)
    if low is not None and value < low:
        status = "below"
    elif high is None or value <= high:
        status = "within"
    else:
        status = "above"
    flagged = status == flag_when
    position = {
        "below": "ниже p10 модели",
        "within": "в диапазоне p10-p90 модели",
        "above": "выше p90 модели",
    }
    comment = f"{name} плана {value:,.0f} {unit} {position[status]}".replace(",", " ")
    if flagged:
        comment += ", план оптимистичнее модели"
    return PlanCheck(
        code=code,
        name=name,
        plan_value=value,
        model=OptionalRange(p10=low, p50=middle, p90=high),
        percentile=percentile(samples, value),
        status=status,
        risk_flag=flagged,
        comment=comment,
    )


def check_plan(request: CreditCheckRequest) -> CreditCheckReport:
    plan = request.plan
    financing = Financing(
        loan_amount_rub=plan.loan_amount_rub,
        rate_annual=plan.rate_annual,
        term_months=plan.term_months,
        schedule=plan.schedule,
    )
    calc = calculate(request.economics.model_copy(update={"financing": financing}))
    checks = [
        plan_check(
            "revenue_month",
            "Выручка в месяц",
            plan.revenue_month_rub,
            calc.inputs.revenue_steady,
            "above",
            "₽",
        )
    ]
    if plan.capex_rub is not None:
        checks.append(plan_check("capex", "Вложения", plan.capex_rub, calc.inputs.capex, "below", "₽"))
    if plan.payback_months is not None:
        checks.append(
            plan_check(
                "payback_months",
                "Окупаемость",
                plan.payback_months,
                calc.metrics.payback_months,
                "below",
                "мес.",
            )
        )
    threshold = calc.settings.dscr_threshold
    probability_ok = float(np.mean(calc.metrics.dscr_min >= threshold)) if plan.loan_amount_rub > 0 else 1.0
    flags = sum(check.risk_flag for check in checks)
    if flags == 0 and probability_ok >= CONFIRMED_DSCR_PROBABILITY:
        verdict = "confirmed"
    elif flags >= REJECTED_FLAGS or probability_ok < REJECTED_DSCR_PROBABILITY:
        verdict = "not_confirmed"
    else:
        verdict = "needs_review"
    summary_lines = [check.comment for check in checks]
    threshold_text = f"{threshold:g}".replace(".", ",")
    dscr_share = f"{probability_ok * PERCENT:.0f}%"
    summary_lines.append(f"Доля сценариев с покрытием долга не ниже {threshold_text} составляет {dscr_share}")
    max_loan = money(calc.metrics.max_loan)
    if plan.loan_amount_rub > max_loan.p50:
        summary_lines.append("Запрошенный кредит больше медианного предельного кредита модели")
    return CreditCheckReport(
        verdict=verdict,
        summary=summary_lines,
        checks=checks,
        loan_amount_rub=plan.loan_amount_rub,
        probability_dscr_ok=probability_ok,
        max_loan_rub=max_loan,
        economics=build_report(calc),
    )


def norms_response(city: str, niche: str) -> NormsResponse:
    city_code = get_city(city).code
    niche_code = get_niche(niche).code
    context = load_context(city_code, niche_code)
    niche_norms = context.norms.niche(niche_code)

    def values(items: Mapping[str, Norm]) -> list[NormValue]:
        return [
            NormValue(
                code=norm.code,
                name=norm.name,
                value=list(norm.value) if isinstance(norm.value, tuple) else norm.value,
                unit=UNIT_LABELS.get(norm.unit, norm.unit),
                source=norm.source,
                note=norm.note,
            )
            for norm in items.values()
        ]

    parameters = []
    for code, (name, unit) in COST_PARAMETERS.items():
        bounds = context.parameters["capex_rub"] if code == "capex_rub" else context.parameters["costs"][code]
        parameters.append(
            ParameterValue(
                code=code,
                name=name,
                p10=float(bounds["p10"]),
                p50=float(bounds["p50"]),
                p90=float(bounds["p90"]),
                unit=unit,
                source=bounds.get("source"),
            )
        )
    return NormsResponse(
        niche=niche_code,
        city=city_code,
        version=context.norms.version,
        unit_name=niche_norms.unit_name,
        discount_rate_annual=context.norms.discount_rate(),
        common=values(context.norms.common),
        niche_norms=values(niche_norms.items),
        parameters=parameters,
    )
