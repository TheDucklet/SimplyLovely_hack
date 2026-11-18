from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from geostart.economics.norms import MONTHS_PER_YEAR


class Schedule(StrEnum):
    ANNUITY = "annuity"
    DIFFERENTIATED = "differentiated"


SCHEDULE_NAMES = {Schedule.ANNUITY: "аннуитетный", Schedule.DIFFERENTIATED: "дифференцированный"}


@dataclass(frozen=True)
class LoanTerms:
    rate_annual: float
    term_months: int
    schedule: Schedule

    def __post_init__(self) -> None:
        if not np.isfinite(self.rate_annual) or self.rate_annual < 0:
            raise ValueError("Ставка кредита должна быть конечной и неотрицательной")
        if self.term_months < 1:
            raise ValueError("Срок кредита должен быть не меньше месяца")

    @property
    def monthly_rate(self) -> float:
        return self.rate_annual / MONTHS_PER_YEAR


def unit_schedule(terms: LoanTerms, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    months = np.arange(horizon)
    active = months < terms.term_months
    rate = terms.monthly_rate
    term = terms.term_months
    if terms.schedule == Schedule.DIFFERENTIATED:
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
