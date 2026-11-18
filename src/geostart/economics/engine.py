from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from geostart.economics.credit import LoanTerms, annual_dscr, loan_schedule, max_loan
from geostart.economics.norms import MONTHS_PER_YEAR
from geostart.economics.taxes import LegalForm, Regime, TaxRules, block_taxes
from geostart.model.finance import employee_contributions

MODEL_VERSION = "economics-0.1.0"
IRR_ITERATIONS = 80
IRR_LOWER_MONTHLY = -0.99
IRR_UPPER_MONTHLY = 1.0
BREAK_EVEN_ITERATIONS = 60
BREAK_EVEN_SEARCH_FACTOR = 20.0
STEADY_LINES = (
    "revenue",
    "cogs",
    "rent",
    "wages",
    "contributions",
    "other",
    "ebitda",
    "main_tax",
    "owner_tax",
    "vat",
    "profit",
)


@dataclass(frozen=True)
class ScenarioInputs:
    revenue_steady: np.ndarray
    area_m2: np.ndarray
    rent_rate: np.ndarray
    staff: np.ndarray
    cogs_share: np.ndarray
    other_opex: np.ndarray
    capex: np.ndarray
    deposit: np.ndarray
    working_capital: np.ndarray
    salary: float

    def __post_init__(self) -> None:
        arrays = {
            "выручка": self.revenue_steady,
            "площадь": self.area_m2,
            "ставка аренды": self.rent_rate,
            "штат": self.staff,
            "доля себестоимости": self.cogs_share,
            "прочие расходы": self.other_opex,
            "вложения": self.capex,
            "залог": self.deposit,
            "оборотный капитал": self.working_capital,
        }
        size = len(self.revenue_steady)
        for name, values in arrays.items():
            if values.shape != (size,):
                raise ValueError(f"Сценарии параметра «{name}» должны иметь одинаковую длину")
            if not np.isfinite(values).all() or (values < 0).any():
                raise ValueError(f"Параметр «{name}» должен быть конечным и неотрицательным")
        if (self.cogs_share >= 1).any():
            raise ValueError("Доля себестоимости должна быть меньше 1")
        if not np.isfinite(self.salary) or self.salary < 0:
            raise ValueError("Зарплата должна быть конечной и неотрицательной")

    @property
    def runs(self) -> int:
        return len(self.revenue_steady)

    @property
    def investment(self) -> np.ndarray:
        return self.capex + self.deposit + self.working_capital


@dataclass(frozen=True)
class PlanSettings:
    horizon: int
    start_month: int
    ramp: tuple[float, ...]
    seasonality: tuple[float, ...]
    revenue_growth: float
    rent_growth: float
    wage_growth: float
    opex_growth: float
    discount_rate: float
    regime: Regime
    legal_form: LegalForm
    loan_amount: np.ndarray
    loan_terms: LoanTerms
    dscr_threshold: float
    rules: TaxRules
    taxes: Mapping[str, object]
    patent_annual: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.horizon < MONTHS_PER_YEAR:
            raise ValueError("Горизонт расчёта должен быть не меньше 12 месяцев")
        if not 1 <= self.start_month <= MONTHS_PER_YEAR:
            raise ValueError("Месяц открытия задаётся числом от 1 до 12")
        if len(self.seasonality) != MONTHS_PER_YEAR:
            raise ValueError("Сезонность задаётся 12 множителями")

    @property
    def monthly_discount(self) -> float:
        return (1.0 + self.discount_rate) ** (1.0 / MONTHS_PER_YEAR) - 1.0


@dataclass(frozen=True)
class Projection:
    revenue: np.ndarray
    cogs: np.ndarray
    rent: np.ndarray
    wages: np.ndarray
    contributions: np.ndarray
    other: np.ndarray
    ebitda: np.ndarray
    main_tax: np.ndarray
    owner_tax: np.ndarray
    vat: np.ndarray
    interest: np.ndarray
    principal: np.ndarray
    loan: np.ndarray
    investment: np.ndarray
    recovery: np.ndarray
    patent_lost: np.ndarray
    general_vat: np.ndarray

    @property
    def taxes(self) -> np.ndarray:
        return self.main_tax + self.owner_tax + self.vat

    @property
    def operating_cash(self) -> np.ndarray:
        return self.ebitda - self.taxes

    @property
    def net_profit(self) -> np.ndarray:
        return self.ebitda - self.interest - self.taxes

    @property
    def owner_cash(self) -> np.ndarray:
        return self.operating_cash - self.interest - self.principal

    @property
    def cumulative_project_cash(self) -> np.ndarray:
        return np.cumsum(self.operating_cash, axis=1) - self.investment[:, None]

    @property
    def cumulative_owner_cash(self) -> np.ndarray:
        return np.cumsum(self.owner_cash, axis=1) - (self.investment - self.loan)[:, None]


def growth_index(rate: float, horizon: int) -> np.ndarray:
    return (1.0 + rate) ** (np.arange(horizon) // MONTHS_PER_YEAR)


def ramp_curve(ramp: tuple[float, ...], horizon: int) -> np.ndarray:
    curve = np.ones(horizon)
    size = min(len(ramp), horizon)
    curve[:size] = ramp[:size]
    return curve


def normalized_seasonality(seasonality: tuple[float, ...]) -> np.ndarray:
    values = np.asarray(seasonality, dtype=float)
    return values / values.mean()


def contributions_by_year(salary: float, settings: PlanSettings) -> np.ndarray:
    years = -(-settings.horizon // MONTHS_PER_YEAR)
    salaries = salary * (1.0 + settings.wage_growth) ** np.arange(years)
    return np.array(
        [employee_contributions(float(value), settings.taxes, settings.rules.niche) for value in salaries]
    )


def allocate(total: np.ndarray, weights: np.ndarray) -> np.ndarray:
    sums = weights.sum(axis=1, keepdims=True)
    shares = np.divide(weights, sums, out=np.full_like(weights, 1.0 / weights.shape[1]), where=sums > 0)
    return total[:, None] * shares


def project(inputs: ScenarioInputs, settings: PlanSettings) -> Projection:
    horizon = settings.horizon
    months = np.arange(horizon)
    calendar = (settings.start_month - 1 + months) % MONTHS_PER_YEAR
    fiscal = (settings.start_month - 1 + months) // MONTHS_PER_YEAR
    opening_year = months // MONTHS_PER_YEAR
    curve = ramp_curve(settings.ramp, horizon) * normalized_seasonality(settings.seasonality)[calendar]
    revenue = inputs.revenue_steady[:, None] * curve * growth_index(settings.revenue_growth, horizon)
    cogs = revenue * inputs.cogs_share[:, None]
    rent = (inputs.area_m2 * inputs.rent_rate)[:, None] * growth_index(settings.rent_growth, horizon)
    wage_index = growth_index(settings.wage_growth, horizon)
    wages = inputs.staff[:, None] * inputs.salary * wage_index
    contributions = inputs.staff[:, None] * contributions_by_year(inputs.salary, settings)[opening_year]
    other = inputs.other_opex[:, None] * growth_index(settings.opex_growth, horizon)
    operating = cogs + rent + wages + contributions + other
    ebitda = revenue - operating
    loan = np.minimum(settings.loan_amount, inputs.investment)
    interest, principal = loan_schedule(loan, settings.loan_terms, horizon)
    main_tax = np.zeros_like(revenue)
    owner_tax = np.zeros_like(revenue)
    vat = np.zeros_like(revenue)
    carry = np.zeros(inputs.runs)
    patent_lost = np.zeros(inputs.runs, dtype=bool)
    general_vat = np.zeros(inputs.runs, dtype=bool)
    for block in np.unique(fiscal):
        mask = fiscal == block
        expenses = operating[:, mask].sum(axis=1) + interest[:, mask].sum(axis=1)
        if block == fiscal[0]:
            expenses = expenses + inputs.capex
        result = block_taxes(
            settings.rules,
            settings.regime,
            settings.legal_form,
            revenue[:, mask].sum(axis=1),
            expenses,
            contributions[:, mask].sum(axis=1),
            inputs.staff,
            int(mask.sum()),
            carry,
            settings.patent_annual,
        )
        carry = result.loss_carry
        weights = revenue[:, mask]
        main_tax[:, mask] = allocate(result.main, weights)
        owner_tax[:, mask] = allocate(result.owner, weights)
        vat[:, mask] = allocate(result.vat, weights)
        patent_lost |= result.patent_lost
        general_vat |= result.general_vat
    return Projection(
        revenue,
        cogs,
        rent,
        wages,
        contributions,
        other,
        ebitda,
        main_tax,
        owner_tax,
        vat,
        interest,
        principal,
        loan,
        inputs.investment,
        inputs.deposit + inputs.working_capital,
        patent_lost,
        general_vat,
    )


def steady_year(inputs: ScenarioInputs, settings: PlanSettings, revenue: np.ndarray) -> dict[str, np.ndarray]:
    cogs = revenue * inputs.cogs_share
    rent = inputs.area_m2 * inputs.rent_rate
    wages = inputs.staff * inputs.salary
    contributions = inputs.staff * employee_contributions(inputs.salary, settings.taxes, settings.rules.niche)
    other = inputs.other_opex
    operating = cogs + rent + wages + contributions + other
    taxes = block_taxes(
        settings.rules,
        settings.regime,
        settings.legal_form,
        revenue * MONTHS_PER_YEAR,
        operating * MONTHS_PER_YEAR,
        contributions * MONTHS_PER_YEAR,
        inputs.staff,
        MONTHS_PER_YEAR,
        np.zeros(inputs.runs),
        settings.patent_annual,
    )
    main = taxes.main / MONTHS_PER_YEAR
    owner = taxes.owner / MONTHS_PER_YEAR
    vat = taxes.vat / MONTHS_PER_YEAR
    ebitda = revenue - operating
    return {
        "revenue": revenue,
        "cogs": cogs,
        "rent": rent,
        "wages": wages,
        "contributions": contributions,
        "other": other,
        "ebitda": ebitda,
        "main_tax": main,
        "owner_tax": owner,
        "vat": vat,
        "profit": ebitda - main - owner - vat,
    }


def break_even_revenue(inputs: ScenarioInputs, settings: PlanSettings) -> np.ndarray:
    fixed = steady_year(inputs, settings, np.zeros(inputs.runs))
    upper = BREAK_EVEN_SEARCH_FACTOR * (
        inputs.revenue_steady + fixed["rent"] + fixed["wages"] + fixed["other"]
    )
    upper = np.maximum(upper, 1.0)
    reachable = steady_year(inputs, settings, upper)["profit"] > 0
    lower = np.zeros(inputs.runs)
    for _ in range(BREAK_EVEN_ITERATIONS):
        middle = (lower + upper) / 2
        positive = steady_year(inputs, settings, middle)["profit"] > 0
        upper = np.where(positive, middle, upper)
        lower = np.where(positive, lower, middle)
    return np.where(reachable, upper, np.nan)


def discount_factors(rate_monthly: np.ndarray | float, horizon: int) -> np.ndarray:
    rate = np.asarray(rate_monthly, dtype=float)
    return (1.0 + rate[..., None]) ** -(np.arange(horizon) + 1.0)


def project_npv(projection: Projection, rate_monthly: np.ndarray | float) -> np.ndarray:
    horizon = projection.revenue.shape[1]
    factors = discount_factors(rate_monthly, horizon)
    flows = projection.operating_cash.copy()
    flows[:, -1] += projection.recovery
    return (flows * factors).sum(axis=-1) - projection.investment


def irr_annual(projection: Projection) -> np.ndarray:
    runs = projection.revenue.shape[0]
    lower = np.full(runs, IRR_LOWER_MONTHLY)
    upper = np.full(runs, IRR_UPPER_MONTHLY)
    valid = (project_npv(projection, lower) > 0) & (project_npv(projection, upper) < 0)
    for _ in range(IRR_ITERATIONS):
        middle = (lower + upper) / 2
        positive = project_npv(projection, middle) > 0
        lower = np.where(positive, middle, lower)
        upper = np.where(positive, upper, middle)
    monthly = (lower + upper) / 2
    return np.where(valid, (1.0 + monthly) ** MONTHS_PER_YEAR - 1.0, np.nan)


def payback(cumulative: np.ndarray, flows: np.ndarray) -> np.ndarray:
    reached = cumulative >= 0
    found = reached.any(axis=1)
    index = np.argmax(reached, axis=1)
    rows = np.arange(len(index))
    previous = np.where(
        index > 0, cumulative[rows, np.maximum(index - 1, 0)], cumulative[rows, 0] - flows[rows, 0]
    )
    step = flows[rows, index]
    fraction = np.divide(-previous, step, out=np.ones(len(index)), where=step > 0)
    return np.where(found, index + np.clip(fraction, 0.0, 1.0), np.nan)


@dataclass(frozen=True)
class Metrics:
    npv: np.ndarray
    irr_annual: np.ndarray
    payback_months: np.ndarray
    discounted_payback_months: np.ndarray
    steady: dict[str, np.ndarray]
    break_even_revenue: np.ndarray
    safety_margin: np.ndarray
    dscr_first_year: np.ndarray
    dscr_min: np.ndarray
    max_loan: np.ndarray
    representative: int

    @property
    def probability_no_payback(self) -> float:
        return float(np.mean(np.isnan(self.payback_months)))

    @property
    def probability_loss(self) -> float:
        return float(np.mean(self.steady["profit"] < 0))


def evaluate(inputs: ScenarioInputs, settings: PlanSettings, projection: Projection) -> Metrics:
    rate = settings.monthly_discount
    flows = projection.operating_cash
    discounted = flows * discount_factors(rate, settings.horizon)
    steady = steady_year(inputs, settings, inputs.revenue_steady)
    break_even = break_even_revenue(inputs, settings)
    safety = np.divide(
        inputs.revenue_steady - break_even,
        inputs.revenue_steady,
        out=np.full(inputs.runs, np.nan),
        where=inputs.revenue_steady > 0,
    )
    dscr_first, dscr_min = annual_dscr(
        flows, projection.interest + projection.principal, settings.loan_terms.term_months
    )
    npv = project_npv(projection, rate)
    order = np.argsort(npv, kind="stable")
    return Metrics(
        npv=npv,
        irr_annual=irr_annual(projection),
        payback_months=payback(projection.cumulative_project_cash, flows),
        discounted_payback_months=payback(
            np.cumsum(discounted, axis=1) - projection.investment[:, None], discounted
        ),
        steady=steady,
        break_even_revenue=break_even,
        safety_margin=safety,
        dscr_first_year=dscr_first,
        dscr_min=dscr_min,
        max_loan=max_loan(steady["profit"] * MONTHS_PER_YEAR, settings.loan_terms, settings.dscr_threshold),
        representative=int(order[len(order) // 2]),
    )


def total_taxes(projection: Projection) -> np.ndarray:
    return projection.taxes.sum(axis=1)


def first_year_taxes(projection: Projection) -> np.ndarray:
    return projection.taxes[:, :MONTHS_PER_YEAR].sum(axis=1)
