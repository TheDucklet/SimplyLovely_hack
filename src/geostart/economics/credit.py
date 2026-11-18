from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from geostart import settings
from geostart.economics.norms import MONTHS_PER_YEAR

PRODUCTS_FILE = Path("credit") / "products.yaml"


class Schedule(StrEnum):
    ANNUITY = "annuity"
    DIFFERENTIATED = "differentiated"


SCHEDULE_NAMES = {Schedule.ANNUITY: "аннуитетный", Schedule.DIFFERENTIATED: "дифференцированный"}


@dataclass(frozen=True)
class LoanTerms:
    rate_annual: float
    term_months: int
    schedule: Schedule
    grace_months: int = 0

    def __post_init__(self) -> None:
        if not np.isfinite(self.rate_annual) or self.rate_annual < 0:
            raise ValueError("Ставка кредита должна быть конечной и неотрицательной")
        if self.term_months < 1:
            raise ValueError("Срок кредита должен быть не меньше месяца")
        if not 0 <= self.grace_months < self.term_months:
            raise ValueError("Льготный период должен быть короче срока кредита")

    @property
    def monthly_rate(self) -> float:
        return self.rate_annual / MONTHS_PER_YEAR


def unit_schedule(terms: LoanTerms, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    grace = min(terms.grace_months, horizon)
    interest, principal = amortizing_schedule(
        terms.monthly_rate, terms.term_months - terms.grace_months, terms.schedule, horizon - grace
    )
    return (
        np.concatenate([np.full(grace, terms.monthly_rate), interest]),
        np.concatenate([np.zeros(grace), principal]),
    )


def amortizing_schedule(
    rate: float, term: int, schedule: Schedule, horizon: int
) -> tuple[np.ndarray, np.ndarray]:
    months = np.arange(horizon)
    active = months < term
    if schedule == Schedule.DIFFERENTIATED:
        principal = np.where(active, 1.0 / term, 0.0)
        balance_before = np.maximum(1.0 - months / term, 0.0)
        return np.where(active, balance_before * rate, 0.0), principal
    if rate == 0:
        return np.zeros(horizon), np.where(active, 1.0 / term, 0.0)
    payment = rate / (1.0 - (1.0 + rate) ** -term)
    growth = (1.0 + rate) ** months
    balance_before = np.maximum(growth - payment * (growth - 1.0) / rate, 0.0)
    interest = np.where(active, balance_before * rate, 0.0)
    principal = np.where(active, payment - interest, 0.0)
    return interest, principal


def loan_schedule(amount: np.ndarray, terms: LoanTerms, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    interest, principal = unit_schedule(terms, horizon)
    return amount[:, None] * interest[None, :], amount[:, None] * principal[None, :]


def peak_annual_service(terms: LoanTerms) -> float:
    years = -(-terms.term_months // MONTHS_PER_YEAR)
    interest, principal = unit_schedule(terms, years * MONTHS_PER_YEAR)
    service = (interest + principal).reshape(years, MONTHS_PER_YEAR).sum(axis=1)
    return float(service.max())


def max_loan(annual_cash: np.ndarray, terms: LoanTerms, dscr_threshold: float) -> np.ndarray:
    return np.maximum(annual_cash, 0.0) / (dscr_threshold * peak_annual_service(terms))


def monthly_dscr(operating_cash: np.ndarray, service: np.ndarray) -> np.ndarray:
    return np.divide(operating_cash, service, out=np.full(operating_cash.shape, np.inf), where=service > 0)


def annual_dscr(
    operating_cash: np.ndarray, service: np.ndarray, term_months: int
) -> tuple[np.ndarray, np.ndarray]:
    horizon = operating_cash.shape[1]
    years = min(-(-term_months // MONTHS_PER_YEAR), -(-horizon // MONTHS_PER_YEAR))
    ratios = []
    for year in range(years):
        window = slice(year * MONTHS_PER_YEAR, min((year + 1) * MONTHS_PER_YEAR, horizon))
        debt = service[:, window].sum(axis=1)
        cash = operating_cash[:, window].sum(axis=1)
        ratios.append(np.divide(cash, debt, out=np.full(len(cash), np.inf), where=debt > 0))
    if not ratios:
        empty = np.full(operating_cash.shape[0], np.inf)
        return empty, empty
    stacked = np.vstack(ratios)
    return stacked[0], stacked.min(axis=0)


@dataclass(frozen=True)
class ProductValue:
    value: float
    source: str | None
    note: str


@dataclass(frozen=True)
class CreditProduct:
    code: str
    name: str
    rate_annual: ProductValue
    max_term_months: ProductValue
    max_amount_rub: ProductValue
    min_business_age_months: ProductValue
    grace_months: ProductValue
    schedule: Schedule


def parse_value(raw: Mapping[str, object]) -> ProductValue:
    value = float(raw["value"])
    if not np.isfinite(value) or value < 0:
        raise ValueError("Условия кредитного продукта должны быть конечными и неотрицательными")
    source = raw.get("source")
    return ProductValue(value, None if source is None else str(source), str(raw.get("note", "")))


def parse_products(raw: Mapping[str, object]) -> dict[str, CreditProduct]:
    return {
        code: CreditProduct(
            code=code,
            name=str(item["name"]),
            rate_annual=parse_value(item["rate_annual"]),
            max_term_months=parse_value(item["max_term_months"]),
            max_amount_rub=parse_value(item["max_amount_rub"]),
            min_business_age_months=parse_value(item["min_business_age_months"]),
            grace_months=parse_value(item["grace_months"]),
            schedule=Schedule(item.get("schedule", Schedule.ANNUITY)),
        )
        for code, item in raw["products"].items()
    }


def products_path() -> Path:
    return settings.research_dir() / PRODUCTS_FILE


@lru_cache(maxsize=4)
def cached_products(path: str, modified_ns: int) -> dict[str, CreditProduct]:
    with Path(path).open(encoding="utf-8") as stream:
        return parse_products(yaml.safe_load(stream))


def load_products() -> dict[str, CreditProduct]:
    path = products_path()
    return cached_products(str(path), path.stat().st_mtime_ns)


def get_product(code: str) -> CreditProduct:
    products = load_products()
    if code not in products:
        raise ValueError(f"Кредитный продукт {code} не найден, доступны: {', '.join(sorted(products))}")
    return products[code]
