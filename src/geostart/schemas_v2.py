from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from geostart.schemas import Assumption, MoneyRange, RiskLevel

RegimeCode = Literal[
    "usn_income_6", "usn_income_minus_expenses_15", "patent", "ausn_income_8", "ausn_income_minus_expenses_20"
]
ScheduleCode = Literal["annuity", "differentiated"]
CheckStatus = Literal["below", "within", "above"]
Verdict = Literal["confirmed", "needs_review", "not_confirmed"]
SensitivityFactorCode = Literal["revenue", "rent", "wages", "cogs_share", "capex"]
SensitivityStressCode = Literal["revenue_minus_20", "rent_plus_15", "rate_plus_3", "combined"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Estimate(StrictModel):
    p10: float = Field(ge=0)
    p50: float = Field(ge=0)
    p90: float = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("Оценка должна соблюдать порядок p10 ≤ p50 ≤ p90")
        return self


class ShareEstimate(Estimate):
    p10: float = Field(ge=0, le=1)
    p50: float = Field(ge=0, le=1)
    p90: float = Field(ge=0, le=1)


class GeoDemand(StrictModel):
    source: Literal["geostart"]
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class RevenueDemand(StrictModel):
    source: Literal["revenue"]
    revenue_month: Estimate
    provider: str | None = Field(default=None, max_length=100)


class TrafficDemand(StrictModel):
    source: Literal["traffic"]
    visitors_per_day: Estimate
    conversion: ShareEstimate
    avg_check_rub: Estimate | None = None
    provider: str | None = Field(default=None, max_length=100)


class GeoSquare(StrictModel):
    square_id: str = Field(min_length=1, max_length=64)
    south: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    spend_rub_month: Estimate
    footfall_day: Estimate | None = None

    @model_validator(mode="after")
    def ordered_bounds(self) -> Self:
        if self.south >= self.north or self.west >= self.east:
            raise ValueError("Границы квадрата должны соблюдать порядок south < north и west < east")
        return self


class GeoPlatformDemand(StrictModel):
    source: Literal["geoplatform"]
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    squares: list[GeoSquare] | None = Field(default=None, min_length=1, max_length=400)
    provider: str | None = Field(default=None, max_length=100)


Demand = Annotated[
    GeoDemand | RevenueDemand | TrafficDemand | GeoPlatformDemand, Field(discriminator="source")
]


class Premises(StrictModel):
    area_m2: float | None = Field(default=None, gt=0, le=10000)
    rent_rub_m2_month: float | None = Field(default=None, gt=0, le=100000)
    security_deposit_months: float | None = Field(default=None, ge=0, le=12)
    central_district: bool | None = None


class Operations(StrictModel):
    staff_count: float | None = Field(default=None, ge=0, le=500)
    salary_rub_month: float | None = Field(default=None, gt=0, le=1000000)
    cogs_share: float | None = Field(default=None, ge=0, lt=1)
    other_opex_rub_month: float | None = Field(default=None, ge=0, le=100000000)


class Investment(StrictModel):
    capex_rub: float | None = Field(default=None, ge=0, le=10000000000)
    working_capital_rub: float | None = Field(default=None, ge=0, le=10000000000)
    franchise_fee_rub: float = Field(default=0, ge=0, le=10000000000)


class Financing(StrictModel):
    loan_amount_rub: float | None = Field(default=None, ge=0, le=10000000000)
    loan_share: float | None = Field(default=None, ge=0, le=1)
    rate_annual: float | None = Field(default=None, ge=0, le=1)
    term_months: int | None = Field(default=None, ge=1, le=360)
    schedule: ScheduleCode | None = None
    grace_months: int | None = Field(default=None, ge=0, le=60)
    product: str | None = Field(default=None, max_length=50)
    business_age_months: int = Field(default=0, ge=0, le=1200)

    @model_validator(mode="after")
    def one_amount(self) -> Self:
        if self.loan_amount_rub is not None and self.loan_share is not None:
            raise ValueError("Укажите сумму кредита или долю кредита во вложениях, но не оба поля")
        return self


class TaxSettings(StrictModel):
    legal_form: Literal["ip", "ooo"] = "ip"
    regime: Literal[
        "auto",
        "usn_income_6",
        "usn_income_minus_expenses_15",
        "patent",
        "ausn_income_8",
        "ausn_income_minus_expenses_20",
    ] = "auto"


class EconomicsRequest(StrictModel):
    city: str
    niche: str
    demand: Demand
    premises: Premises = Field(default_factory=Premises)
    operations: Operations = Field(default_factory=Operations)
    investment: Investment = Field(default_factory=Investment)
    financing: Financing | None = None
    tax: TaxSettings = Field(default_factory=TaxSettings)
    horizon_months: int = Field(default=36, ge=12, le=120)
    start_month: int | None = Field(default=None, ge=1, le=12)
    start_year: int | None = Field(default=None, ge=2025, le=2040)
    discount_rate_annual: float | None = Field(default=None, ge=0, le=1)


class SensitivityRequest(EconomicsRequest):
    shift_share: float = Field(default=0.2, ge=0.05, le=0.5)


class OptionalRange(BaseModel):
    p10: float | None
    p50: float | None
    p90: float | None


class Versions(BaseModel):
    model: str
    norms: str
    data: str
    taxes: str


class SensitivityMetrics(BaseModel):
    profit_steady_month_p50: float
    npv_p50: float
    payback_months_p50: float | None


class SensitivitySummary(SensitivityMetrics):
    probability_no_payback_24: float = Field(ge=0, le=1)


class SensitivityPoint(SensitivityMetrics):
    change: float


class SensitivityFactor(BaseModel):
    code: SensitivityFactorCode
    name: str
    low: SensitivityPoint
    high: SensitivityPoint


class SensitivityStress(SensitivitySummary):
    code: SensitivityStressCode
    name: str


class SensitivityReport(BaseModel):
    versions: Versions
    shift_share: float
    base: SensitivitySummary
    factors: list[SensitivityFactor]
    stresses: list[SensitivityStress]


class DemandSummary(BaseModel):
    source: Literal["geostart", "revenue", "traffic", "geoplatform"]
    provider: str | None
    revenue_steady_month: MoneyRange
    h3: str | None
    district: str | None


class RegimeOption(BaseModel):
    regime: RegimeCode
    name: str
    eligible: bool
    reason: str | None
    taxes_first_year_p50: float | None
    taxes_horizon_p50: float | None
    contributions_horizon_p50: float | None
    burden_horizon_p50: float | None


class TaxSummary(BaseModel):
    regime: RegimeCode
    name: str
    legal_form: Literal["ip", "ooo"]
    chosen_automatically: bool
    explanation: str
    options: list[RegimeOption]


class InvestmentItem(BaseModel):
    code: str
    name: str
    amount: float
    life_months: int | None


class InvestmentSummary(BaseModel):
    capex: float
    franchise_fee: float
    security_deposit: float
    working_capital: float
    total: MoneyRange
    loan: float
    own_funds: float
    items: list[InvestmentItem]


class SteadyMonth(BaseModel):
    revenue: float
    cogs: float
    rent: float
    wages: float
    payroll_contributions: float
    other: float
    ebitda: float
    tax: float
    owner_contributions: float
    vat: float
    profit: float


class MonthRow(BaseModel):
    month: int
    calendar_month: int
    revenue: float
    cogs: float
    rent: float
    payroll: float
    other: float
    taxes: float
    ebitda: float
    depreciation: float
    interest: float
    principal: float
    net_profit: float
    owner_cash_flow: float
    cumulative_project_cash: float
    dscr: float | None


class CashBand(BaseModel):
    month: int
    p10: float
    p50: float
    p90: float


class YearRow(BaseModel):
    year: int
    revenue: float
    operating_costs: float
    ebitda: float
    depreciation: float
    ebit: float
    taxes: float
    interest: float
    principal: float
    net_profit: float
    operating_cash_flow: float


class EconomicsMetrics(BaseModel):
    npv: MoneyRange
    irr_annual: OptionalRange
    payback_months: OptionalRange
    discounted_payback_months: OptionalRange
    first_profit_month: OptionalRange
    probability_no_payback: float
    probability_loss: float
    risk_level: RiskLevel
    profit_steady_month: MoneyRange
    ebitda_margin_p50: float | None
    break_even_revenue_month: OptionalRange
    break_even_units_per_day: OptionalRange
    safety_margin: OptionalRange
    unit_name: str
    unit_value_rub: float
    contribution_margin_per_unit: float


class CreditSummary(BaseModel):
    product: str | None
    product_name: str | None
    amount: float
    rate_annual: float
    term_months: int
    grace_months: int
    schedule: ScheduleCode
    first_payment: float
    total_interest: float
    dscr_first_year: OptionalRange
    dscr_min: OptionalRange
    dscr_monthly_min: OptionalRange
    months_below_threshold_p50: float
    dscr_threshold: float
    probability_dscr_below_threshold: float
    max_loan_rub: MoneyRange


class EconomicsReport(BaseModel):
    city: str
    niche: str
    versions: Versions
    scenarios: int
    horizon_months: int
    start_month: int
    start_year: int
    discount_rate_annual: float
    demand: DemandSummary
    tax: TaxSummary
    investment: InvestmentSummary
    steady_month: SteadyMonth
    metrics: EconomicsMetrics
    credit: CreditSummary
    monthly: list[MonthRow]
    cash_band: list[CashBand]
    years: list[YearRow]
    assumptions: list[Assumption]
    warnings: list[str]


class BusinessPlan(StrictModel):
    revenue_month_rub: float = Field(gt=0, le=10000000000)
    capex_rub: float | None = Field(default=None, gt=0, le=10000000000)
    payback_months: float | None = Field(default=None, gt=0, le=600)
    loan_amount_rub: float = Field(ge=0, le=10000000000)
    rate_annual: float | None = Field(default=None, ge=0, le=1)
    term_months: int | None = Field(default=None, ge=1, le=360)
    schedule: ScheduleCode | None = None
    grace_months: int | None = Field(default=None, ge=0, le=60)
    product: str | None = Field(default=None, max_length=50)
    business_age_months: int = Field(default=0, ge=0, le=1200)


class CreditCheckRequest(StrictModel):
    economics: EconomicsRequest
    plan: BusinessPlan


class PlanCheck(BaseModel):
    code: Literal["revenue_month", "capex", "payback_months"]
    name: str
    plan_value: float
    model: OptionalRange
    percentile: float | None
    status: CheckStatus
    risk_flag: bool
    comment: str


class CreditCheckReport(BaseModel):
    verdict: Verdict
    summary: list[str]
    checks: list[PlanCheck]
    loan_amount_rub: float
    probability_dscr_ok: float
    max_loan_rub: MoneyRange
    economics: EconomicsReport


class NormValue(BaseModel):
    code: str
    name: str
    value: float | list[float]
    unit: str
    source: str | None
    note: str


class ParameterValue(BaseModel):
    code: str
    name: str
    p10: float
    p50: float
    p90: float
    unit: str
    source: str | None


class NormsResponse(BaseModel):
    niche: str
    city: str
    version: str
    unit_name: str
    discount_rate_annual: float
    common: list[NormValue]
    niche_norms: list[NormValue]
    parameters: list[ParameterValue]


class ProductCondition(BaseModel):
    value: float
    source: str | None
    note: str


class CreditProductInfo(BaseModel):
    code: str
    name: str
    rate_annual: ProductCondition
    max_term_months: ProductCondition
    max_amount_rub: ProductCondition
    min_business_age_months: ProductCondition
    grace_months: ProductCondition
    schedule: ScheduleCode
