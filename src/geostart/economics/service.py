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
from geostart.economics.credit import (
    CreditProduct,
    LoanTerms,
    ProductValue,
    Schedule,
    get_product,
    load_products,
)
from geostart.economics.engine import (
    DEFAULT_ASSET_LIFE_MONTHS,
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
from geostart.economics.geoplatform import (
    PLATFORM_ORDERS_ERROR,
    STUB_PROVIDER,
    SquareLayer,
    load_stub,
    platform_revenue,
)
from geostart.economics.norms import MONTHS_PER_YEAR, Norm, Norms, load_norms, norms_path
from geostart.economics.sampling import bounds_samples, optional_summary, quantile_samples, summary
from geostart.economics.taxes import (
    AUSN_REGIMES,
    MOSCOW,
    REGIME_NAMES,
    LegalForm,
    PatentCost,
    Regime,
    TaxRules,
    patent_cost,
    tax_rules,
)
from geostart.model.assumptions import fallback_salary_assumption, profession_salary
from geostart.model.demand import DEFAULT_RUNS, DEFAULT_SEED, DemandKind, demand_kind
from geostart.model.finance import HIGH_RISK_THRESHOLD, MEDIUM_RISK_THRESHOLD
from geostart.research import city_parameters
from geostart.schemas import Assumption, MoneyRange
from geostart.schemas_v2 import (
    CashBand,
    CreditCheckReport,
    CreditCheckRequest,
    CreditProductInfo,
    CreditSummary,
    DemandSummary,
    EconomicsMetrics,
    EconomicsReport,
    EconomicsRequest,
    Financing,
    GeoDemand,
    GeoPlatformDemand,
    GeoSquare,
    InvestmentItem,
    InvestmentSummary,
    MonthRow,
    NormsResponse,
    NormValue,
    OptionalRange,
    ParameterValue,
    PlanCheck,
    ProductCondition,
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
FRANCHISE_NAME = "Паушальный взнос"
MAX_COGS_SHARE = 0.99
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
    salary_fallback: bool = False


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
    salary, version, fallback = city_salary(settings.processed_dir(city) / "wages.parquet", parameters)
    return EconomicContext(
        city, niche, parameters, taxes, pd.read_csv(rent_path), salary, version, load_norms(), fallback
    )


def city_salary(path: Path, parameters: Mapping[str, object]) -> tuple[float | None, str, bool]:
    if not path.is_file():
        return None, UNKNOWN_DATA_VERSION, False
    wages = pd.read_parquet(path)
    if wages.empty:
        return None, UNKNOWN_DATA_VERSION, False
    version = pd.to_datetime(wages["collected_at"]).max().date().isoformat()
    salary, fallback = profession_salary(wages, str(parameters["costs"]["wage_profession"]))
    return salary, version, fallback


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


@dataclass(frozen=True)
class PointLocation:
    inputs: object
    cell: str
    district: str
    central: bool | None
    rent_rate: float
    samples: pd.DataFrame
    model: object
    index: int


def point_location(context: EconomicContext, lat: float, lon: float) -> PointLocation:
    from geostart.model.service import (
        cached_location,
        city_context,
        input_revision,
        load_inputs,
        rent_rates,
        validate_location,
    )

    inputs = load_inputs(context.city, context.niche)
    validate_location(inputs, lat, lon, context.city)
    cell = h3.latlng_to_cell(lat, lon, get_city(context.city).h3_resolution)
    samples = city_context(context.city, context.niche).samples
    features, index, model = cached_location(
        context.city, context.niche, input_revision(context.city, context.niche), cell
    )
    row = features.iloc[[index]]
    district = str(row.district.iloc[0])
    central = None
    if context.city == MOSCOW:
        okrug = inputs.district_okrugs.get(district)
        central = None if okrug is None else okrug == CENTRAL_OKRUG
    return PointLocation(
        inputs, cell, district, central, float(rent_rates(inputs, row)[0]), samples, model, index
    )


def geo_demand(context: EconomicContext, demand: GeoDemand) -> DemandSamples:
    from geostart.model.simulation import simulate_revenues

    point = point_location(context, demand.lat, demand.lon)
    revenue = simulate_revenues(point.model, point.samples, point.index)[:, 0]
    note = Assumption(
        name="Источник выручки",
        value="Модель Хаффа ГеоСтарт по открытым данным, 200 сценариев параметров спроса",
        unit="",
        source="https://www.openstreetmap.org",
    )
    return DemandSamples(
        revenue, "geostart", None, point.cell, point.district, point.rent_rate, point.central, [note]
    )


def request_layers(squares: list[GeoSquare]) -> list[SquareLayer]:
    return [
        SquareLayer(
            square.square_id,
            square.south,
            square.west,
            square.north,
            square.east,
            square.spend_rub_month.p10,
            square.spend_rub_month.p50,
            square.spend_rub_month.p90,
            None if square.footfall_day is None else square.footfall_day.p50,
        )
        for square in squares
    ]


def platform_demand(context: EconomicContext, demand: GeoPlatformDemand) -> DemandSamples:
    if demand_kind(context.niche) != DemandKind.VISITS:
        raise ValueError(PLATFORM_ORDERS_ERROR)
    point = point_location(context, demand.lat, demand.lon)
    layers = request_layers(demand.squares) if demand.squares else load_stub(context.city, context.niche)
    provider = demand.provider or (None if demand.squares else STUB_PROVIDER)
    result = platform_revenue(
        point.inputs.features,
        point.inputs.competitors,
        context.niche,
        point.samples,
        layers,
        demand.lat,
        demand.lon,
        DEFAULT_SEED,
    )
    label = provider or "данные геоплатформы из запроса"
    notes = [
        Assumption(
            name="Источник выручки",
            value=(
                f"Траты категории по квадратам 500 м ({label}), разнесённые по ячейкам H3 и разделённые "
                "с конкурентами по модели Хаффа ГеоСтарт"
            ),
            unit="",
            source=None,
        ),
        Assumption(
            name="Квадратов геоплатформы в радиусе доступности",
            value=float(result.squares_used),
            unit="шт.",
            source=None,
        ),
        Assumption(
            name="Траты категории в этих квадратах, p50",
            value=result.spend_in_reach_p50,
            unit="₽/месяц",
            source=None,
        ),
    ]
    if result.footfall_p50 is not None:
        notes.append(
            Assumption(
                name="Поток людей в этих квадратах, p50",
                value=result.footfall_p50,
                unit="чел./день",
                source=None,
            )
        )
    return DemandSamples(
        result.revenue,
        "geoplatform",
        provider,
        point.cell,
        point.district,
        point.rent_rate,
        point.central,
        notes,
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
    if isinstance(demand, GeoPlatformDemand):
        return platform_demand(context, demand)
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
    return sampled


@dataclass(frozen=True)
class Adjustments:
    revenue: float = 1.0
    rent: float = 1.0
    wages: float = 1.0
    cogs_share: float = 1.0
    capex: float = 1.0
    loan_rate_add: float = 0.0


DEFAULT_ADJUSTMENTS = Adjustments()


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
    product: CreditProduct | None
    explanation: str


def money_text(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def loan_terms(
    context: EconomicContext,
    financing: Financing | None,
    warnings: list[str],
    *,
    rate_add: float = 0.0,
) -> tuple[LoanTerms, CreditProduct | None]:
    norms = context.norms
    product = get_product(financing.product) if financing and financing.product else None
    rate = norms.value("loan_rate_annual") if product is None else product.rate_annual.value
    term = int(norms.value("loan_term_months")) if product is None else int(product.max_term_months.value)
    grace = 0 if product is None else int(product.grace_months.value)
    schedule = Schedule.ANNUITY if product is None else product.schedule
    if financing is not None:
        rate = financing.rate_annual if financing.rate_annual is not None else rate
        term = financing.term_months if financing.term_months is not None else term
        grace = financing.grace_months if financing.grace_months is not None else grace
        schedule = Schedule(financing.schedule) if financing.schedule else schedule
    if product is not None and financing is not None:
        if term > product.max_term_months.value:
            warnings.append(
                f"Срок {term} мес. больше предельного срока продукта «{product.name}» "
                f"{product.max_term_months.value:g} мес."
            )
        if financing.business_age_months < product.min_business_age_months.value:
            warnings.append(
                f"Продукт «{product.name}» требует бизнес не младше "
                f"{product.min_business_age_months.value:g} мес., для нового бизнеса нужен другой продукт"
            )
    if grace >= term:
        raise ValueError("Льготный период должен быть короче срока кредита")
    return LoanTerms(rate + rate_add, term, schedule, grace), product


def loan_amount(financing: Financing | None, investment: np.ndarray) -> np.ndarray:
    if financing is None:
        return np.zeros_like(investment)
    if financing.loan_amount_rub is not None:
        return np.full_like(investment, financing.loan_amount_rub)
    if financing.loan_share is not None:
        return investment * financing.loan_share
    return np.zeros_like(investment)


def regime_eligibility(
    regime: Regime,
    legal_form: LegalForm,
    patent: PatentCost | None,
    staff: np.ndarray,
    rules: TaxRules,
    start: date,
) -> str | None:
    staff_p50 = float(np.median(staff))
    if regime == Regime.PATENT:
        if legal_form != LegalForm.IP:
            return "Патент доступен только ИП"
        if patent is None:
            return "Стоимость патента для ниши и города не исследована"
        if staff_p50 > rules.patent_staff_limit:
            return f"Штат больше {rules.patent_staff_limit:g} человек"
    if regime in AUSN_REGIMES:
        ausn = rules.ausn
        if ausn is None:
            return "АУСН в нише не исследована"
        if ausn.region_start is None:
            return "Нет данных о введении АУСН в регионе города"
        if start < ausn.region_start:
            return f"АУСН в регионе действует с {ausn.region_start:%d.%m.%Y}"
        if start.year > ausn.end_year:
            return f"Эксперимент АУСН завершается 31.12.{ausn.end_year}"
        if staff_p50 > ausn.staff_limit:
            return f"Штат больше {ausn.staff_limit:g} человек"
    return None


def start_date(month: int | None, year: int | None) -> date:
    today = date.today()
    if month is None:
        month = today.month % MONTHS_PER_YEAR + 1
        default_year = today.year + (1 if today.month == MONTHS_PER_YEAR else 0)
    else:
        default_year = today.year if month > today.month else today.year + 1
    return date(year or default_year, month, 1)


def regime_explanation(chosen: Regime, options: list[RegimeOption], automatic: bool) -> str:
    if not automatic:
        return f"Режим {REGIME_NAMES[chosen]} задан в запросе"
    selected = next(option for option in options if option.regime == chosen.value)
    others = [
        option
        for option in options
        if option.eligible and option.regime != chosen.value and option.burden_horizon_p50 is not None
    ]
    if not others or selected.burden_horizon_p50 is None:
        return f"Режим {REGIME_NAMES[chosen]} выбран как единственный доступный"
    runner = min(others, key=lambda option: option.burden_horizon_p50)
    gap = runner.burden_horizon_p50 - selected.burden_horizon_p50
    return (
        f"Режим {REGIME_NAMES[chosen]} выбран по наименьшей сумме налогов и взносов за горизонт расчёта, "
        f"он дешевле режима {runner.name} на {money_text(gap)} ₽ по медиане сценариев"
    )


def calculate(
    request: EconomicsRequest,
    *,
    adjustments: Adjustments = DEFAULT_ADJUSTMENTS,
    demand: DemandSamples | None = None,
) -> Calculation:
    city = get_city(request.city).code
    niche = get_niche(request.niche).code
    context = load_context(city, niche)
    norms = context.norms
    niche_norms = norms.niche(niche)
    if demand is None:
        demand = resolve_demand(context, request)
    runs = len(demand.revenue)
    costs = cost_samples(context, request, runs)
    warnings: list[str] = []
    start = start_date(request.start_month, request.start_year)
    if request.premises.rent_rub_m2_month is not None:
        rent_rate, rent_source = request.premises.rent_rub_m2_month, None
    elif demand.rent_rate is not None:
        rent_rate, rent_source = demand.rent_rate, rent_reference(context.rents, demand.district)
    else:
        rent_rate, rent_source = city_rent(context.rents), rent_reference(context.rents, None)
    rent_rate *= adjustments.rent
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
    revenue = demand.revenue * adjustments.revenue
    cogs_share = np.minimum(costs["cogs_share_of_revenue"] * adjustments.cogs_share, MAX_COGS_SHARE)
    working_capital = (
        np.full(runs, request.investment.working_capital_rub)
        if request.investment.working_capital_rub is not None
        else niche_norms.value("working_capital_cogs_months") * revenue * cogs_share
    )
    inputs = ScenarioInputs(
        revenue_steady=revenue,
        area_m2=area,
        rent_rate=np.full(runs, float(rent_rate)),
        staff=costs["staff_count"],
        cogs_share=cogs_share,
        other_opex=costs["other_opex_rub"],
        capex=costs["capex_rub"] * adjustments.capex,
        deposit=deposit_months * area * rent_rate,
        working_capital=working_capital,
        franchise_fee=np.full(runs, float(request.investment.franchise_fee_rub)),
        salary=float(salary) * adjustments.wages,
    )
    rules = tax_rules(context.taxes, niche, city)
    central = (
        request.premises.central_district if request.premises.central_district is not None else demand.central
    )
    patent = patent_cost(context.taxes, city, niche, area, niche_norms.value("hall_share_of_area"), central)
    legal_form = LegalForm(request.tax.legal_form)
    terms, product = loan_terms(context, request.financing, warnings, rate_add=adjustments.loan_rate_add)
    loan = loan_amount(request.financing, inputs.investment)
    if (loan > inputs.investment).any():
        warnings.append("Сумма кредита больше вложений, в расчёте кредит ограничен суммой вложений")
    if product is not None and float(np.median(loan)) > product.max_amount_rub.value:
        warnings.append(
            f"Сумма кредита больше лимита продукта «{product.name}» "
            f"{money_text(product.max_amount_rub.value)} ₽"
        )
    base = {
        "horizon": request.horizon_months,
        "start_month": start.month,
        "start_year": start.year,
        "capex_lives": tuple((item.share, item.life_months) for item in niche_norms.capex.items),
        "franchise_life_months": DEFAULT_ASSET_LIFE_MONTHS,
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
    burdens: dict[Regime, float] = {}
    for regime in Regime:
        reason = regime_eligibility(regime, legal_form, patent, inputs.staff, rules, start)
        first = horizon = contributions = burden = None
        if reason is None:
            plan = PlanSettings(regime=regime, **base)
            result = project(inputs, plan)
            projections[regime] = (plan, result)
            first = float(np.median(first_year_taxes(result)))
            horizon = float(np.median(total_taxes(result)))
            contributions = float(np.median(result.contributions.sum(axis=1)))
            burden = float(np.median(total_taxes(result) + result.contributions.sum(axis=1)))
            burdens[regime] = burden
        options.append(
            RegimeOption(
                regime=regime.value,
                name=REGIME_NAMES[regime],
                eligible=reason is None,
                reason=reason,
                taxes_first_year_p50=first,
                taxes_horizon_p50=horizon,
                contributions_horizon_p50=contributions,
                burden_horizon_p50=burden,
            )
        )
    automatic = request.tax.regime == "auto"
    if automatic:
        chosen = min(burdens, key=burdens.__getitem__)
    else:
        chosen = Regime(request.tax.regime)
        if chosen not in projections:
            reason = next(option.reason for option in options if option.regime == chosen.value)
            raise ValueError(f"Режим {REGIME_NAMES[chosen]} недоступен: {reason}")
    plan, result = projections[chosen]
    metrics = evaluate(inputs, plan, result)
    if result.fallback.any() and chosen == Regime.PATENT:
        warnings.append(
            f"В {result.fallback.mean() * PERCENT:.0f}% сценариев выручка или штат выше лимитов патента, "
            "для них налог посчитан по УСН «Доходы»"
        )
    if result.fallback.any() and chosen in AUSN_REGIMES:
        warnings.append(
            f"В {result.fallback.mean() * PERCENT:.0f}% сценариев выручка или штат выше лимитов АУСН, "
            "для них налог и взносы посчитаны по УСН"
        )
    if result.ausn_ended:
        warnings.append(
            "Эксперимент АУСН завершается 31.12.2027, с 2028 года налог и взносы посчитаны по УСН"
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
        product,
        regime_explanation(chosen, options, automatic),
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
    if calc.salary_source and context.salary_fallback:
        result.append(
            fallback_salary_assumption(
                str(context.parameters["costs"]["wage_profession"]), calc.inputs.salary
            )
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
    ausn = calc.settings.rules.ausn
    if regime in AUSN_REGIMES and ausn is not None:
        result.append(
            Assumption(
                name="Фиксированный взнос на травматизм на АУСН",
                value=ausn.injury_annual,
                unit="₽/год",
                source=ausn.source,
            )
        )
        result.append(
            Assumption(
                name="Начало АУСН в регионе",
                value=f"{ausn.region_start:%d.%m.%Y}" if ausn.region_start else "нет данных",
                unit="",
                source=ausn.region_source,
            )
        )
    structure = context.norms.niche(context.niche).capex
    result.append(
        Assumption(
            name="Структура вложений и сроки амортизации"
            + ("" if structure.source else " – допущение без источника"),
            value=", ".join(
                f"{item.name} {item.share * PERCENT:.0f}% на {item.life_months} мес."
                for item in structure.items
            ),
            unit="",
            source=structure.source,
        )
    )
    if calc.product is not None:
        result.append(
            Assumption(
                name=f"Ставка продукта «{calc.product.name}»",
                value=calc.product.rate_annual.value,
                unit="доля в год",
                source=calc.product.rate_annual.source,
            )
        )
    if calc.settings.legal_form == LegalForm.IP and regime not in AUSN_REGIMES:
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
    dscr = calc.metrics.dscr_monthly[r]
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
            depreciation=float(p.depreciation[r, month]),
            interest=float(p.interest[r, month]),
            principal=float(p.principal[r, month]),
            net_profit=float(p.net_profit[r, month]),
            owner_cash_flow=float(p.owner_cash[r, month]),
            cumulative_project_cash=float(cumulative[month]),
            dscr=float(dscr[month]) if np.isfinite(dscr[month]) else None,
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
                depreciation=float(p.depreciation[r, window].sum()),
                ebit=float(p.ebit[r, window].sum()),
                taxes=float(p.taxes[r, window].sum()),
                interest=float(p.interest[r, window].sum()),
                principal=float(p.principal[r, window].sum()),
                net_profit=float(p.net_profit[r, window].sum()),
                operating_cash_flow=float(p.operating_cash[r, window].sum()),
            )
        )
    return rows


def investment_items(calc: Calculation) -> list[InvestmentItem]:
    capex = float(np.median(calc.inputs.capex))
    structure = calc.context.norms.niche(calc.context.niche).capex
    items = [
        InvestmentItem(
            code=item.code, name=item.name, amount=capex * item.share, life_months=item.life_months
        )
        for item in structure.items
    ]
    fee = float(np.median(calc.inputs.franchise_fee))
    if fee > 0:
        items.append(
            InvestmentItem(
                code="franchise_fee", name=FRANCHISE_NAME, amount=fee, life_months=DEFAULT_ASSET_LIFE_MONTHS
            )
        )
    items.append(
        InvestmentItem(
            code="security_deposit",
            name="Обеспечительный платёж по аренде",
            amount=float(np.median(calc.inputs.deposit)),
            life_months=None,
        )
    )
    items.append(
        InvestmentItem(
            code="working_capital",
            name="Оборотный запас",
            amount=float(np.median(calc.inputs.working_capital)),
            life_months=None,
        )
    )
    return items


def calculation_versions(context: EconomicContext) -> Versions:
    return Versions(
        model=MODEL_VERSION,
        norms=context.norms.version,
        data=context.data_version,
        taxes=str(context.taxes.get("updated", context.taxes.get("year"))),
    )


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
        versions=calculation_versions(context),
        scenarios=calc.inputs.runs,
        horizon_months=calc.settings.horizon,
        start_month=calc.settings.start_month,
        start_year=calc.settings.start_year,
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
            explanation=calc.explanation,
            options=calc.options,
        ),
        investment=InvestmentSummary(
            capex=float(np.median(calc.inputs.capex)),
            franchise_fee=float(np.median(calc.inputs.franchise_fee)),
            security_deposit=float(np.median(calc.inputs.deposit)),
            working_capital=float(np.median(calc.inputs.working_capital)),
            total=money(calc.inputs.investment),
            loan=float(np.median(p.loan)),
            own_funds=float(np.median(calc.inputs.investment - p.loan)),
            items=investment_items(calc),
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
            first_profit_month=optional(m.first_profit_month),
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
            product=None if calc.product is None else calc.product.code,
            product_name=None if calc.product is None else calc.product.name,
            amount=float(np.median(p.loan)),
            rate_annual=terms.rate_annual,
            term_months=terms.term_months,
            grace_months=terms.grace_months,
            schedule=terms.schedule.value,
            first_payment=float(np.median(p.interest[:, 0] + p.principal[:, 0])),
            total_interest=float(np.median(p.interest.sum(axis=1))),
            dscr_first_year=optional(m.dscr_first_year),
            dscr_min=optional(m.dscr_min),
            dscr_monthly_min=optional(m.dscr_monthly_min),
            months_below_threshold_p50=float(np.median(m.months_below(threshold))) if loan_active else 0.0,
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
        grace_months=plan.grace_months,
        product=plan.product,
        business_age_months=plan.business_age_months,
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


def condition(value: ProductValue) -> ProductCondition:
    return ProductCondition(value=value.value, source=value.source, note=value.note)


def credit_products() -> list[CreditProductInfo]:
    return [
        CreditProductInfo(
            code=product.code,
            name=product.name,
            rate_annual=condition(product.rate_annual),
            max_term_months=condition(product.max_term_months),
            max_amount_rub=condition(product.max_amount_rub),
            min_business_age_months=condition(product.min_business_age_months),
            grace_months=condition(product.grace_months),
            schedule=product.schedule.value,
        )
        for product in load_products().values()
    ]
