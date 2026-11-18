from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from geostart import settings

MONTHS_PER_YEAR = 12
NORMS_FILE = Path("economics") / "norms.yaml"
COMMON_NORMS = (
    "key_rate_annual",
    "risk_premium_annual",
    "inflation_annual",
    "rent_indexation_annual",
    "wage_growth_annual",
    "opex_indexation_annual",
    "loan_rate_annual",
    "loan_term_months",
    "dscr_threshold",
)
NICHE_NORMS = (
    "ramp_up_share",
    "seasonality",
    "working_capital_cogs_months",
    "security_deposit_months",
    "hall_share_of_area",
)
NORM_NAMES = {
    "key_rate_annual": "Ключевая ставка Банка России",
    "risk_premium_annual": "Премия за риск малого бизнеса",
    "inflation_annual": "Прогноз инфляции и индексация цен",
    "rent_indexation_annual": "Индексация аренды",
    "wage_growth_annual": "Рост зарплат",
    "opex_indexation_annual": "Индексация прочих расходов",
    "loan_rate_annual": "Ставка кредита по умолчанию",
    "loan_term_months": "Срок кредита по умолчанию",
    "dscr_threshold": "Минимальный коэффициент покрытия долга",
    "ramp_up_share": "Выход на плановую выручку по месяцам",
    "seasonality": "Сезонность по календарным месяцам",
    "working_capital_cogs_months": "Оборотный запас",
    "security_deposit_months": "Обеспечительный платёж",
    "hall_share_of_area": "Доля зала в площади",
}


@dataclass(frozen=True)
class Norm:
    code: str
    value: float | tuple[float, ...]
    unit: str
    source: str | None
    note: str

    @property
    def name(self) -> str:
        return NORM_NAMES.get(self.code, self.code)


@dataclass(frozen=True)
class CapexItem:
    code: str
    name: str
    share: float
    life_months: int


@dataclass(frozen=True)
class CapexStructure:
    items: tuple[CapexItem, ...]
    source: str | None
    note: str


@dataclass(frozen=True)
class NicheNorms:
    unit_name: str
    unit_value_parameter: str
    items: Mapping[str, Norm]
    capex: CapexStructure

    def value(self, code: str) -> float:
        return float(self.items[code].value)

    def series(self, code: str) -> tuple[float, ...]:
        value = self.items[code].value
        return value if isinstance(value, tuple) else (float(value),)


@dataclass(frozen=True)
class Norms:
    version: str
    common: Mapping[str, Norm]
    niches: Mapping[str, NicheNorms]

    def value(self, code: str) -> float:
        return float(self.common[code].value)

    def niche(self, code: str) -> NicheNorms:
        if code not in self.niches:
            raise ValueError(f"Для ниши {code} нет нормативов финансового движка")
        return self.niches[code]

    def discount_rate(self) -> float:
        return self.value("key_rate_annual") + self.value("risk_premium_annual")


def parse_norm(code: str, raw: Mapping[str, object]) -> Norm:
    value = raw.get("value")
    if isinstance(value, list):
        parsed: float | tuple[float, ...] = tuple(float(item) for item in value)
        numbers = np.array(parsed)
    else:
        parsed = float(value)
        numbers = np.array([parsed])
    if numbers.size == 0 or not np.isfinite(numbers).all() or (numbers < 0).any():
        raise ValueError(f"Норматив {code} должен быть конечным и неотрицательным")
    source = raw.get("source")
    return Norm(
        code, parsed, str(raw.get("unit", "")), None if source is None else str(source), str(raw["note"])
    )


def validate_niche(code: str, items: Mapping[str, Norm]) -> None:
    ramp = np.array(items["ramp_up_share"].value, dtype=float, ndmin=1)
    if (ramp <= 0).any() or (ramp > 1).any():
        raise ValueError(f"Выход на план ниши {code} задаётся долями от 0 до 1")
    seasonality = np.array(items["seasonality"].value, dtype=float, ndmin=1)
    if seasonality.size != MONTHS_PER_YEAR or (seasonality <= 0).any():
        raise ValueError(f"Сезонность ниши {code} задаётся 12 положительными множителями")
    if not 0 <= float(items["hall_share_of_area"].value) <= 1:
        raise ValueError(f"Доля зала ниши {code} должна быть от 0 до 1")


def parse_capex(niche: str, raw: Mapping[str, object]) -> CapexStructure:
    items = tuple(
        CapexItem(str(code), str(item["name"]), float(item["share"]), int(item["life_months"]))
        for code, item in raw["items"].items()
    )
    shares = np.array([item.share for item in items])
    if not items or (shares < 0).any() or not np.isclose(shares.sum(), 1.0):
        raise ValueError(f"Доли статей вложений ниши {niche} должны быть неотрицательными и давать в сумме 1")
    if any(item.life_months < 1 for item in items):
        raise ValueError(f"Срок использования статей вложений ниши {niche} должен быть не меньше месяца")
    source = raw.get("source")
    return CapexStructure(items, None if source is None else str(source), str(raw["note"]))


def parse_norms(raw: Mapping[str, object]) -> Norms:
    common_raw = raw["common"]
    missing = [code for code in COMMON_NORMS if code not in common_raw]
    if missing:
        raise ValueError(f"В нормативах нет значений {', '.join(missing)}")
    common = {code: parse_norm(code, common_raw[code]) for code in COMMON_NORMS}
    if common["dscr_threshold"].value <= 0 or common["loan_term_months"].value < 1:
        raise ValueError("Порог покрытия долга и срок кредита должны быть положительными")
    niches = {}
    for niche, block in raw["niches"].items():
        absent = [code for code in (*NICHE_NORMS, "capex_structure") if code not in block]
        if absent:
            raise ValueError(f"В нормативах ниши {niche} нет значений {', '.join(absent)}")
        items = {code: parse_norm(code, block[code]) for code in NICHE_NORMS}
        validate_niche(niche, items)
        niches[niche] = NicheNorms(
            str(block["unit_name"]),
            str(block["unit_value_parameter"]),
            items,
            parse_capex(niche, block["capex_structure"]),
        )
    return Norms(str(raw["version"]), common, niches)


def norms_path() -> Path:
    return settings.research_dir() / NORMS_FILE


@lru_cache(maxsize=4)
def cached_norms(path: str, modified_ns: int) -> Norms:
    with Path(path).open(encoding="utf-8") as stream:
        return parse_norms(yaml.safe_load(stream))


def load_norms() -> Norms:
    path = norms_path()
    return cached_norms(str(path), path.stat().st_mtime_ns)
