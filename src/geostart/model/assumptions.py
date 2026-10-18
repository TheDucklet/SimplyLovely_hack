from collections.abc import Mapping
from enum import StrEnum

import numpy as np
import pandas as pd

from geostart.model.demand import MIN_DISTANCE_M, SEATS_SCALE, niche_defaults
from geostart.model.finance import MONTHS_PER_YEAR, TaxRegime, employee_contributions, vat_band
from geostart.schemas import Assumption


class WageBasis(StrEnum):
    PROXY = "proxy"
    DIRECT = "direct"


PARAMETER_NAMES = {
    "avg_check_rub": "Средний чек",
    "visits_per_resident_month": "Посещения на жителя в месяц",
    "visits_per_worker_month": "Посещения на рабочее место в месяц",
    "orders_per_resident_month": "Заказы на жителя в месяц",
    "marketplace_share": "Доля маркетплейса",
    "payout_per_order_rub": "Выплата за заказ",
    "max_walk_distance_m": "Предельное расстояние пешком",
    "distance_decay_beta": "Степень убывания с расстоянием",
    "outside_option_weight": "Вес внешней альтернативы",
    "metro_visits_per_month": "Покупки прохожих у метро в месяц",
    "metro_influence_distance_m": "Радиус влияния метро",
    "transit_visits_per_stop_month": "Покупки прохожих на остановку в месяц",
    "max_pickup_distance_m": "Расширенный радиус получения заказа",
    "max_cups_per_day": "Пропускная способность кофейни, чашек в день",
}
PROFESSION_NAMES = {"barista": "бариста", "pickup_operator": "оператора пункта выдачи"}


def tax_assumptions(
    taxes: Mapping[str, object],
    niche: str,
    salary: float,
    revenues: np.ndarray,
    usn_p50: float,
    vat_values: np.ndarray,
    regime: str,
) -> list[Assumption]:
    contribution = employee_contributions(salary, taxes, niche)
    rules = taxes.get("social_contributions_employer", {})
    reduced = rules.get("msp_reduced_rate_above_1_5_mrot", {})
    reduced_applies = niche in reduced.get("applies_to", []) and niche in rules.get(
        "msp_threshold_1_5_mrot", {}
    ).get("applies_to", [])
    source = (
        reduced.get("source")
        if reduced_applies
        else rules.get("standard_rate", taxes["employer_contributions_rate"]).get("source")
    )
    result = [
        Assumption(
            name="Эффективный тариф взносов работодателя",
            value=contribution / salary * 100 if salary > 0 else 0.0,
            unit="% зарплаты",
            source=source,
        ),
        Assumption(name="Взносы на одного сотрудника", value=contribution, unit="₽/месяц", source=source),
        Assumption(
            name="Налог УСН в месяц",
            value=usn_p50,
            unit="₽/месяц",
            source=taxes[
                "usn_income_rate" if regime == TaxRegime.INCOME else "usn_income_minus_expenses_rate"
            ].get("source"),
        ),
    ]
    if reduced_applies:
        result.append(
            Assumption(
                name="Условия пониженного тарифа взносов",
                value=(
                    "Предполагаются включение в реестр МСП, основной ОКВЭД 56 и доля доходов "
                    "от основной деятельности не менее 70%. Порог применяется к зарплате одного сотрудника."
                ),
                unit="",
                source=source,
            )
        )
    band = vat_band(taxes, niche)
    result.append(
        Assumption(
            name="НДС в месяц",
            value=float(np.median(vat_values)),
            unit="₽/месяц",
            source=None if band is None else band.source,
        )
    )
    result.append(
        Assumption(
            name="НДС p90 за месяц",
            value=float(np.quantile(vat_values, 0.9)),
            unit="₽/месяц",
            source=None if band is None else band.source,
        )
    )
    if band is not None:
        annual = revenues * MONTHS_PER_YEAR
        selected = (annual > band.lower) & (annual <= band.upper)
        result.extend(
            [
                Assumption(
                    name="Специальная ставка НДС без вычетов",
                    value=band.rate * 100,
                    unit="% выручки",
                    source=band.source,
                ),
                Assumption(
                    name="Порог и предел специальной ставки НДС",
                    value=(
                        f"Годовая выручка больше {band.lower:,.0f} и не больше {band.upper:,.0f} ₽"
                    ).replace(",", " "),
                    unit="",
                    source=band.source,
                ),
                Assumption(
                    name="Доля сценариев с НДС по специальной ставке",
                    value=float(np.mean(selected) * 100),
                    unit="%",
                    source=band.source,
                ),
            ]
        )
        if np.any(annual > band.upper):
            upper_label = f"{band.upper:,.0f}".replace(",", " ")
            result.append(
                Assumption(
                    name="Предупреждение о НДС",
                    value=(
                        f"В {np.mean(annual > band.upper) * 100:g}% сценариев годовая выручка выше "
                        f"{upper_label} ₽. НДС этих сценариев не рассчитан, ставки 7% и 22% вне MVP."
                    ),
                    unit="",
                    source=band.source,
                )
            )
    return result


def demand_assumptions(parameters: Mapping[str, object]) -> list[Assumption]:
    assumptions = []
    if parameters.get("status") == "placeholder":
        assumptions.append(
            Assumption(
                name="Параметры исследования",
                value="Условные значения до проверки источников",
                unit="",
                source=None,
            )
        )
    for name, bounds in parameters["demand"].items():
        if bounds.get("source") is None:
            assumptions.append(
                Assumption(
                    name=PARAMETER_NAMES.get(name, name),
                    value=str(bounds.get("note") or "Источник не подтверждён"),
                    unit="",
                    source=None,
                )
            )
    if "outside_option_weight" not in parameters["demand"]:
        defaults = niche_defaults(parameters.get("niche", "coffee"))["outside_option_weight"]
        lower = defaults["p10"]
        upper = defaults["p90"]
        assumptions.append(
            Assumption(
                name="Вес внешней альтернативы",
                value=f"Равномерный диапазон {lower}-{upper}",
                unit="",
                source=None,
            )
        )
    assumptions.extend(
        [
            Assumption(name="Нижняя граница расстояния модели", value=MIN_DISTANCE_M, unit="м", source=None),
            Assumption(
                name="Масштаб роста привлекательности по местам", value=SEATS_SCALE, unit="мест", source=None
            ),
        ]
    )
    return assumptions


def wage_assumptions(wages: pd.DataFrame, profession: str) -> list[Assumption]:
    selected = wages.loc[wages["profession"].eq(profession) & wages["basis"].eq(WageBasis.PROXY)]
    profession_name = PROFESSION_NAMES.get(profession, profession)
    return [
        Assumption(
            name=f"Зарплата {profession_name} по соседней профессии из-за нехватки вакансий",
            value=float(row.salary_p50),
            unit="₽/месяц",
            source="https://opendata.trudvsem.ru",
        )
        for row in selected.itertuples(index=False)
    ]


def resolve_rent(rents: pd.DataFrame, district: str) -> tuple[float, list[Assumption]]:
    column = "rent_rub_m2_month_p50"
    values = pd.to_numeric(rents[column], errors="coerce")
    valid = values.notna() & np.isfinite(values) & values.gt(0)
    if not valid.any():
        raise ValueError("Нет положительных ставок аренды, загрузите ставки города")
    matching = values.loc[valid & rents["zone"].eq(district)]
    if not matching.empty:
        return float(matching.median()), []
    median = float(values.loc[valid].median())
    return median, [
        Assumption(
            name=f"Аренда района {district} по медиане ставок p50 города",
            value=median,
            unit="₽/м² в месяц",
            source=None,
        )
    ]
