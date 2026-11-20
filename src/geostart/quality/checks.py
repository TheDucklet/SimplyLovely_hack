from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd
import yaml

from geostart.config import CityConfig, get_city, load_cities, load_niches
from geostart.settings import REPOSITORY_ROOT, config_dir

ERROR = "error"
WARNING = "warning"
HEX_COLUMNS = [
    "h3",
    "lat",
    "lon",
    "district",
    "residents",
    "workers",
    "offices_n",
    "education_n",
    "malls_n",
    "transit_stops_n",
    "metro_dist_m",
]
COUNT_COLUMNS = ["offices_n", "education_n", "malls_n", "transit_stops_n"]
COMPETITOR_COLUMNS = ["poi_id", "niche", "name", "lat", "lon", "h3", "source"]
COMPETITOR_SOURCES = {"osm", "mos_ru"}
ADDRESS_COLUMNS = ["address", "lat", "lon", "h3"]
WAGE_COLUMNS = [
    "profession",
    "salary_p25",
    "salary_p50",
    "salary_p75",
    "vacancies_n",
    "collected_at",
    "basis",
]
SCORE_COLUMNS = ["h3", "revenue_p10", "revenue_p50", "revenue_p90", "profit_p50", "risk_level"]
RISK_LEVELS = {"low", "medium", "high"}


@dataclass(frozen=True)
class Result:
    city: str
    dataset: str
    check: str
    severity: str
    passed: bool
    detail: str = ""


def load_limits(path: Path | None = None) -> dict:
    return yaml.safe_load((path or config_dir() / "quality.yaml").read_text(encoding="utf-8"))


def find_key(value: object, key: str) -> object:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for item in value.values():
            if (found := find_key(item, key)) is not None:
                return found
    return None


def wage_professions() -> dict[str, str]:
    professions = {}
    for niche in load_niches():
        params = yaml.safe_load((REPOSITORY_ROOT / niche.params_file).read_text(encoding="utf-8"))
        profession = find_key(params, "wage_profession")
        if profession:
            professions[niche.code] = str(profession)
    return professions


def share(mask: pd.Series) -> str:
    return f"{float(mask.mean()):.1%}".replace(".", ",") if len(mask) else "0%"


class CityChecks:
    def __init__(self, root: Path, city: CityConfig, limits: dict, today: date | None = None) -> None:
        self.root = root
        self.city = city
        self.limits = limits
        self.today = today or date.today()
        self.folder = root / "processed" / city.code
        self.bbox: tuple[float, float, float, float] | None = None
        self.cells: set[str] = set()

    def result(
        self, dataset: str, check: str, passed: bool, detail: str = "", severity: str = ERROR
    ) -> Result:
        return Result(self.city.code, dataset, check, severity, bool(passed), detail)

    def columns(self, dataset: str, frame: pd.DataFrame, required: list[str]) -> Result:
        missing = [column for column in required if column not in frame.columns]
        return self.result(dataset, "есть все поля", not missing, ", ".join(missing))

    def inside(self, dataset: str, frame: pd.DataFrame) -> Result:
        if self.bbox is None:
            return self.result(
                dataset, "координаты внутри границы города", True, "граница не загружена", WARNING
            )
        west, south, east, north = self.bbox
        outside = ~(frame["lon"].between(west, east) & frame["lat"].between(south, north))
        return self.result(
            dataset,
            "координаты внутри границы города",
            not outside.any(),
            f"вне границы {int(outside.sum())}",
        )

    def in_cells(self, dataset: str, frame: pd.DataFrame, severity: str = ERROR) -> Result:
        foreign = ~frame["h3"].isin(self.cells)
        return self.result(
            dataset, "ячейка есть в сетке города", not foreign.any(), f"чужих {int(foreign.sum())}", severity
        )

    def boundary(self) -> Iterator[Result]:
        path = self.folder / "boundary.geojson"
        if not path.exists():
            yield self.result("boundary", "файл есть", False, str(path.name))
            return
        shape = gpd.read_file(path)
        geometry = shape.geometry.union_all() if len(shape) else None
        valid = geometry is not None and not geometry.is_empty and geometry.is_valid
        yield self.result("boundary", "многоугольник корректен", valid)
        if valid:
            margin = self.limits["bbox_margin_deg"]
            west, south, east, north = geometry.bounds
            self.bbox = (west - margin, south - margin, east + margin, north + margin)

    def hexes(self) -> Iterator[Result]:
        frame = pd.read_parquet(self.folder / "hex_features.parquet")
        yield self.columns("hex_features", frame, HEX_COLUMNS)
        yield self.result("hex_features", "есть строки", len(frame) > 0, f"строк {len(frame)}")
        self.cells = set(frame["h3"])
        valid = frame["h3"].map(
            lambda cell: h3.is_valid_cell(cell) and h3.get_resolution(cell) == self.city.h3_resolution
        )
        yield self.result(
            "hex_features",
            f"ячейки H3 разрешения {self.city.h3_resolution}",
            valid.all(),
            f"неверных {int((~valid).sum())}",
        )
        yield self.result("hex_features", "ячейки не повторяются", frame["h3"].is_unique)
        yield self.inside("hex_features", frame)
        filled = ["h3", "lat", "lon", "residents", "workers", *COUNT_COLUMNS]
        empty = {column: int(frame[column].isna().sum()) for column in filled if frame[column].isna().any()}
        yield self.result("hex_features", "нет пропусков в признаках", not empty, str(empty) if empty else "")
        negative = [
            column for column in ["residents", "workers", *COUNT_COLUMNS] if (frame[column] < 0).any()
        ]
        yield self.result("hex_features", "признаки не отрицательные", not negative, ", ".join(negative))
        too_many = [
            column for column in COUNT_COLUMNS if (frame[column] > self.limits["counts_max_per_cell"]).any()
        ]
        yield self.result(
            "hex_features", "счётчики объектов в пределах", not too_many, ", ".join(too_many), WARNING
        )
        low, high = self.limits["metro_dist_m"]
        metro = frame["metro_dist_m"].dropna()
        yield self.result(
            "hex_features",
            f"расстояние до метро от {low} до {high} м",
            metro.between(low, high).all(),
            f"заполнено {share(frame['metro_dist_m'].notna())}",
        )
        empty_residents = frame["residents"] == 0
        yield self.result(
            "hex_features",
            "доля ячеек без жителей",
            float(empty_residents.mean()) <= self.limits["empty_residents_share_warning"],
            share(empty_residents),
            WARNING,
        )
        unknown = frame["district"].fillna("") == ""
        yield self.result(
            "hex_features",
            "у ячейки определён район",
            float(unknown.mean()) <= self.limits["unknown_district_share_warning"],
            f"без района {share(unknown)}",
            WARNING,
        )

    def competitors(self) -> Iterator[Result]:
        frame = pd.read_parquet(self.folder / "competitors.parquet")
        yield self.columns("competitors", frame, COMPETITOR_COLUMNS)
        niches = {niche.code for niche in load_niches()}
        unknown = sorted(set(frame["niche"]) - niches)
        yield self.result("competitors", "ниша из справочника", not unknown, ", ".join(unknown))
        missing = sorted(niches - set(frame["niche"]))
        yield self.result(
            "competitors", "есть конкуренты каждой ниши", not missing, ", ".join(missing), WARNING
        )
        sources = sorted(set(frame["source"]) - COMPETITOR_SOURCES)
        yield self.result("competitors", "источник osm или mos_ru", not sources, ", ".join(sources))
        repeated = int(frame.duplicated(["poi_id", "niche"]).sum())
        yield self.result(
            "competitors", "объект не повторяется внутри ниши", repeated == 0, f"повторов {repeated}"
        )
        yield self.inside("competitors", frame)
        yield self.in_cells("competitors", frame)
        if "seats" in frame.columns:
            negative = int((frame["seats"].dropna() < 0).sum())
            yield self.result(
                "competitors", "посадочные места не отрицательные", negative == 0, f"отрицательных {negative}"
            )

    def addresses(self) -> Iterator[Result]:
        path = self.folder / "addresses.parquet"
        if not path.exists():
            yield self.result("addresses", "файл есть", False, path.name, WARNING)
            return
        frame = pd.read_parquet(path)
        yield self.columns("addresses", frame, ADDRESS_COLUMNS)
        yield self.result("addresses", "есть строки", len(frame) > 0, f"строк {len(frame)}", WARNING)
        blank = frame["address"].fillna("").str.strip() == ""
        yield self.result("addresses", "адрес не пустой", not blank.any(), f"пустых {int(blank.sum())}")
        yield self.inside("addresses", frame)
        yield self.in_cells("addresses", frame)

    def wages(self) -> Iterator[Result]:
        frame = pd.read_parquet(self.folder / "wages.parquet")
        yield self.columns("wages", frame, WAGE_COLUMNS)
        needed = set(wage_professions().values())
        missing = sorted(needed - set(frame["profession"]))
        yield self.result(
            "wages",
            "есть зарплата каждой профессии ниш",
            not missing,
            f"нет {', '.join(missing)}" if missing else "",
            WARNING,
        )
        ordered = (frame["salary_p25"] <= frame["salary_p50"]) & (frame["salary_p50"] <= frame["salary_p75"])
        yield self.result("wages", "p25 ≤ p50 ≤ p75", ordered.all(), f"нарушений {int((~ordered).sum())}")
        low, high = self.limits["salary_rub_month"]
        outside = ~frame["salary_p50"].between(low, high)
        yield self.result(
            "wages",
            f"медиана зарплаты от {low:,} до {high:,} ₽".replace(",", " "),
            not outside.any(),
            ", ".join(frame.loc[outside, "profession"]),
        )
        few = frame.loc[frame["vacancies_n"] < self.limits["min_vacancies"], "profession"]
        yield self.result(
            "wages", f"не меньше {self.limits['min_vacancies']} вакансий", few.empty, ", ".join(few), WARNING
        )
        collected = pd.to_datetime(frame["collected_at"]).dt.date
        future = collected > self.today
        yield self.result("wages", "дата сбора не в будущем", not future.any())
        age = (self.today - collected.min()).days if len(collected) else 0
        yield self.result(
            "wages",
            f"зарплаты моложе {self.limits['wages_max_age_days']} дней",
            age <= self.limits["wages_max_age_days"],
            f"старейшая запись {age} дн.",
            WARNING,
        )

    def scores(self) -> Iterator[Result]:
        for niche in load_niches():
            path = self.root / "scores" / f"{self.city.code}_{niche.code}.parquet"
            dataset = f"scores/{niche.code}"
            if not path.exists():
                yield self.result(dataset, "расчёт есть", False, path.name, WARNING)
                continue
            frame = pd.read_parquet(path)
            yield self.columns(dataset, frame, SCORE_COLUMNS)
            covered = set(frame["h3"]) == self.cells
            yield self.result(
                dataset, "расчёт покрывает все ячейки", covered, f"ячеек {len(frame)} из {len(self.cells)}"
            )
            ordered = (frame["revenue_p10"] <= frame["revenue_p50"]) & (
                frame["revenue_p50"] <= frame["revenue_p90"]
            )
            yield self.result(
                dataset, "выручка p10 ≤ p50 ≤ p90", ordered.all(), f"нарушений {int((~ordered).sum())}"
            )
            limit = self.limits["revenue_rub_month_max"]
            outside = ~frame["revenue_p50"].between(0, limit)
            yield self.result(
                dataset,
                "выручка p50 от 0 до 50 млн ₽ в месяц",
                not outside.any(),
                f"вне {int(outside.sum())}",
            )
            levels = sorted(set(frame["risk_level"]) - RISK_LEVELS)
            yield self.result(dataset, "уровень риска из справочника", not levels, ", ".join(levels))

    def run(self) -> list[Result]:
        if not (self.folder / "hex_features.parquet").exists():
            return [self.result("processed", "данные города есть", False, str(self.folder))]
        results = [*self.boundary(), *self.hexes()]
        for part in (self.competitors, self.addresses, self.wages, self.scores):
            results.extend(part())
        return results


def run_checks(root: Path, cities: list[str] | None = None, today: date | None = None) -> list[Result]:
    limits = load_limits()
    codes = cities or [city.code for city in load_cities() if (root / "processed" / city.code).exists()]
    return [result for code in codes for result in CityChecks(root, get_city(code), limits, today).run()]


def errors(results: list[Result]) -> list[Result]:
    return [result for result in results if not result.passed and result.severity == ERROR]


def warnings(results: list[Result]) -> list[Result]:
    return [result for result in results if not result.passed and result.severity == WARNING]


def as_json(results: list[Result]) -> list[dict]:
    return [asdict(result) for result in results]
