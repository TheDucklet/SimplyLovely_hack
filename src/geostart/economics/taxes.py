from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from geostart.economics.norms import MONTHS_PER_YEAR

PATENT_RATE = 0.06
MOSCOW = "moscow"
TULA = "tula"


class Regime(StrEnum):
    USN_INCOME = "usn_income_6"
    USN_PROFIT = "usn_income_minus_expenses_15"
    PATENT = "patent"


class LegalForm(StrEnum):
    IP = "ip"
    OOO = "ooo"


REGIME_NAMES = {
    Regime.USN_INCOME: "УСН «Доходы» 6%",
    Regime.USN_PROFIT: "УСН «Доходы минус расходы» 15%",
    Regime.PATENT: "Патентная система",
}


def rule_value(section: Mapping[str, object], name: str, niche: str) -> float:
    item = section[name]
    applies = item.get("applies_to")
    if applies is not None and niche not in applies:
        return 0.0
    return float(item["value"])


@dataclass(frozen=True)
class TaxRules:
    niche: str
    usn_income_rate: float
    usn_profit_rate: float
    minimum_tax_rate: float
    reduction_limit_with_staff: float
    reduction_limit_without_staff: float
    owner_fixed_annual: float
    owner_threshold: float
    owner_extra_rate: float
    owner_extra_cap: float
    vat_exemption: float
    vat_tier1_rate: float
    vat_tier1_max: float
    vat_tier2_rate: float
    vat_tier2_max: float
    vat_general_rate: float
    vat_applies: bool
    patent_applies: bool
    patent_revenue_limit: float
    patent_staff_limit: float
    sources: Mapping[str, str | None]


def tax_rules(taxes: Mapping[str, object], niche: str) -> TaxRules:
    usn = taxes["usn"]
    owner = taxes["ip_self_contributions"]
    vat = taxes["vat_on_usn"]
    patent = taxes.get("patent_system", {})
    patent_applies = bool(patent) and niche in patent["max_annual_revenue_limit"]["applies_to"]
    return TaxRules(
        niche=niche,
        usn_income_rate=float(taxes["usn_income_rate"]["value"]),
        usn_profit_rate=float(taxes["usn_income_minus_expenses_rate"]["value"]),
        minimum_tax_rate=float(usn["min_tax_rate_profit_object"]["value"]),
        reduction_limit_with_staff=float(usn["tax_deduction_max_share_with_staff"]["value"]),
        reduction_limit_without_staff=float(usn["tax_deduction_max_share_ip_no_staff"]["value"]),
        owner_fixed_annual=rule_value(owner, "fixed_annual", niche),
        owner_threshold=rule_value(owner, "additional_income_threshold", niche),
        owner_extra_rate=rule_value(owner, "additional_rate_above_threshold", niche),
        owner_extra_cap=rule_value(owner, "additional_annual_cap", niche),
        vat_exemption=float(vat["exemption_revenue_threshold"]["value"]),
        vat_tier1_rate=float(vat["special_rate_tier1"]["value"]),
        vat_tier1_max=float(vat["special_rate_tier1_max_revenue"]["value"]),
        vat_tier2_rate=float(vat["special_rate_tier2"]["value"]),
        vat_tier2_max=float(vat["special_rate_tier2_max_revenue"]["value"]),
        vat_general_rate=float(vat["general_rate"]["value"]),
        vat_applies=niche in vat["special_rate_tier1"]["applies_to"],
        patent_applies=patent_applies,
        patent_revenue_limit=float(patent["max_annual_revenue_limit"]["value"]) if patent_applies else 0.0,
        patent_staff_limit=float(patent["max_staff_limit"]["value"]) if patent_applies else 0.0,
        sources={
            Regime.USN_INCOME: taxes["usn_income_rate"].get("source"),
            Regime.USN_PROFIT: taxes["usn_income_minus_expenses_rate"].get("source"),
            Regime.PATENT: patent["max_annual_revenue_limit"].get("source") if patent_applies else None,
            "owner": owner["fixed_annual"].get("source"),
            "vat": vat["special_rate_tier1"].get("source"),
        },
    )


@dataclass(frozen=True)
class PatentCost:
    annual: np.ndarray
    description: str
    source: str | None


def patent_cost(
    taxes: Mapping[str, object],
    city: str,
    niche: str,
    area_m2: np.ndarray,
    hall_share: float,
    central: bool | None,
) -> PatentCost | None:
    rules = taxes.get("patent_system", {})
    if not rules or niche not in rules["max_annual_revenue_limit"]["applies_to"]:
        return None
    with_hall = hall_share > 0
    if city == MOSCOW:
        kind = "with_hall" if with_hall else "no_hall"
        bound = "min" if central is False else "max"
        item = rules[f"moscow_{niche}_{kind}_annual_{bound}"]
        place = "вне ЦАО по минимальной ставке" if central is False else "по ставке ЦАО"
        if central is None:
            place = "по ставке ЦАО, так как округ точки не задан"
        return PatentCost(
            np.full(len(area_m2), float(item["value"])), f"Патент в Москве {place}", item.get("source")
        )
    if city == TULA:
        if with_hall:
            item = rules[f"tula_{niche}_with_hall_annual_per_m2"]
            annual = float(item["value"]) * area_m2 * hall_share
            return PatentCost(annual, "Патент в Туле по площади зала", item.get("source"))
        item = rules[f"tula_{niche}_no_hall_annual_per_object"]
        return PatentCost(
            np.full(len(area_m2), float(item["value"])), "Патент в Туле без зала", item.get("source")
        )
    return None


def owner_contributions(rules: TaxRules, base: np.ndarray, months: int) -> np.ndarray:
    extra = np.minimum(
        np.maximum(base - rules.owner_threshold, 0.0) * rules.owner_extra_rate, rules.owner_extra_cap
    )
    return rules.owner_fixed_annual * months / MONTHS_PER_YEAR + extra


def vat_rates(rules: TaxRules, annual_revenue: np.ndarray) -> np.ndarray:
    if not rules.vat_applies:
        return np.zeros_like(annual_revenue)
    return np.select(
        [
            annual_revenue <= rules.vat_exemption,
            annual_revenue <= rules.vat_tier1_max,
            annual_revenue <= rules.vat_tier2_max,
        ],
        [0.0, rules.vat_tier1_rate, rules.vat_tier2_rate],
        rules.vat_general_rate,
    )


@dataclass(frozen=True)
class BlockTaxes:
    main: np.ndarray
    owner: np.ndarray
    vat: np.ndarray
    loss_carry: np.ndarray
    patent_lost: np.ndarray
    general_vat: np.ndarray


def income_tax(
    rules: TaxRules, revenue: np.ndarray, contributions: np.ndarray, owner: np.ndarray, staff: np.ndarray
) -> np.ndarray:
    gross = revenue * rules.usn_income_rate
    limit = np.where(staff > 0, rules.reduction_limit_with_staff, rules.reduction_limit_without_staff)
    return gross - np.minimum(contributions + owner, gross * limit)


def block_taxes(
    rules: TaxRules,
    regime: Regime,
    legal_form: LegalForm,
    revenue: np.ndarray,
    expenses: np.ndarray,
    contributions: np.ndarray,
    staff: np.ndarray,
    months: int,
    loss_carry: np.ndarray,
    patent_annual: np.ndarray | None,
) -> BlockTaxes:
    annual_revenue = revenue * MONTHS_PER_YEAR / months
    is_ip = legal_form == LegalForm.IP
    no_patent = np.zeros(len(revenue), dtype=bool)
    if regime == Regime.USN_PROFIT:
        margin = revenue - expenses
        owner = (
            owner_contributions(rules, np.maximum(margin, 0.0), months) if is_ip else np.zeros_like(revenue)
        )
        profit = margin - owner
        used = np.minimum(loss_carry, np.maximum(profit, 0.0))
        base = np.maximum(profit - used, 0.0)
        main = np.maximum(base * rules.usn_profit_rate, revenue * rules.minimum_tax_rate)
        carry = loss_carry - used + np.maximum(-profit, 0.0)
        vat = revenue * vat_rates(rules, annual_revenue)
        return BlockTaxes(main, owner, vat, carry, no_patent, annual_revenue > rules.vat_tier2_max)
    owner = owner_contributions(rules, revenue, months) if is_ip else np.zeros_like(revenue)
    main = income_tax(rules, revenue, contributions, owner, staff)
    vat = revenue * vat_rates(rules, annual_revenue)
    lost = no_patent
    if regime == Regime.PATENT:
        if patent_annual is None or not is_ip:
            raise ValueError("Патент доступен только ИП в нишах и городах с исследованной стоимостью")
        lost = (annual_revenue > rules.patent_revenue_limit) | (staff > rules.patent_staff_limit)
        cost = patent_annual * months / MONTHS_PER_YEAR
        patent_owner = owner_contributions(rules, patent_annual / PATENT_RATE, months)
        limit = np.where(staff > 0, rules.reduction_limit_with_staff, rules.reduction_limit_without_staff)
        patent_main = cost - np.minimum(contributions + patent_owner, cost * limit)
        main = np.where(lost, main, patent_main)
        owner = np.where(lost, owner, patent_owner)
        vat = np.where(lost, vat, 0.0)
    return BlockTaxes(main, owner, vat, loss_carry, lost, annual_revenue > rules.vat_tier2_max)
