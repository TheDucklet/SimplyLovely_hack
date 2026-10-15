from collections.abc import Mapping
from enum import StrEnum

import numpy as np
import pandas as pd

from geostart.model.demand import MIN_DISTANCE_M, SEATS_SCALE, niche_defaults
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
}
PROFESSION_NAMES = {"barista": "бариста", "pickup_operator": "оператора пункта выдачи"}


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
