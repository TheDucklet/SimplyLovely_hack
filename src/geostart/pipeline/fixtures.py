import argparse
import json
from functools import cache
from pathlib import Path

import h3
import numpy as np
import pandas as pd

from geostart.config import CityConfig, get_city, load_cities, load_niches
from geostart.settings import processed_dir

FIXTURE_SEED = 2026
FIXTURE_RING_RADIUS = 31
FIXTURE_COLLECTED_AT = pd.Timestamp("2026-10-15")
POINT_JITTER_DEGREES = 0.0008
ADDRESSES_PER_CITY = 1500

HEX_FEATURE_COLUMNS = [
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
COMPETITOR_COLUMNS = ["poi_id", "niche", "name", "brand", "lat", "lon", "h3", "source", "seats"]
WAGE_COLUMNS = [
    "profession",
    "salary_p25",
    "salary_p50",
    "salary_p75",
    "vacancies_n",
    "collected_at",
    "basis",
]
ADDRESS_COLUMNS = ["address", "lat", "lon", "h3"]

DISTRICTS = {
    "moscow": [
        "Тверской",
        "Пресненский",
        "Хамовники",
        "Замоскворечье",
        "Таганский",
        "Басманный",
        "Мещанский",
        "Арбат",
    ],
    "tula": ["Центральный", "Советский", "Привокзальный", "Пролетарский", "Зареченский"],
}
CITIES_WITH_METRO = {"moscow"}
COMPETITOR_COUNTS = {
    "moscow": {"coffee": 450, "pickup_point": 900},
    "tula": {"coffee": 90, "pickup_point": 220},
}
COMPETITOR_TITLES = {"coffee": "Кофейня", "pickup_point": "Пункт выдачи"}
PICKUP_BRANDS = ["Ozon", "Wildberries", "Яндекс Маркет"]
MOS_RU_SHARE = 0.3
WAGE_MEDIANS = {
    "moscow": {"barista": 72000, "pickup_operator": 65000},
    "tula": {"barista": 42000, "pickup_operator": 40000},
}
STREET_NAMES = ["Тестовая улица", "Синтетический переулок", "Модельный проспект", "Пробная улица"]


def city_rng(city: CityConfig, salt: int = 0) -> np.random.Generator:
    return np.random.default_rng(FIXTURE_SEED + salt + sum(map(ord, city.code)))


def center_cell(city: CityConfig) -> str:
    return h3.latlng_to_cell(city.center[0], city.center[1], city.h3_resolution)


def fixture_cells(city: CityConfig) -> list[str]:
    return sorted(h3.grid_disk(center_cell(city), FIXTURE_RING_RADIUS))


def assign_districts(city: CityConfig, latitudes: np.ndarray, longitudes: np.ndarray) -> list[str]:
    districts = DISTRICTS[city.code]
    angles = np.arctan2(latitudes - city.center[0], longitudes - city.center[1])
    sectors = ((angles + np.pi) / (2 * np.pi) * len(districts)).astype(int) % len(districts)
    return [districts[sector] for sector in sectors]


@cache
def build_hex_features(city_code: str) -> pd.DataFrame:
    city = get_city(city_code)
    rng = city_rng(city)
    cells = fixture_cells(city)
    coordinates = np.array([h3.cell_to_latlng(cell) for cell in cells])
    ring_distance = np.array([h3.grid_distance(center_cell(city), cell) for cell in cells])
    closeness = 1 - ring_distance / (FIXTURE_RING_RADIUS + 1)
    residents = rng.lognormal(np.log(800 + 2200 * closeness), 0.6)
    workers = rng.lognormal(np.log(200 + 7000 * closeness**3), 0.8)
    if city.code in CITIES_WITH_METRO:
        metro_dist_m = rng.uniform(80, 2500, len(cells)) * (1.3 - closeness)
    else:
        metro_dist_m = np.full(len(cells), np.nan)
    frame = pd.DataFrame(
        {
            "h3": cells,
            "lat": coordinates[:, 0],
            "lon": coordinates[:, 1],
            "district": assign_districts(city, coordinates[:, 0], coordinates[:, 1]),
            "residents": residents.round(1),
            "workers": workers.round(1),
            "offices_n": rng.poisson(0.3 + 6 * closeness**3).astype("int64"),
            "education_n": rng.poisson(0.4, len(cells)).astype("int64"),
            "malls_n": rng.poisson(0.05 + 0.3 * closeness**2).astype("int64"),
            "transit_stops_n": rng.poisson(1.5 + 2 * closeness).astype("int64"),
            "metro_dist_m": metro_dist_m.round(0),
        }
    )
    return frame[HEX_FEATURE_COLUMNS]


def sample_points(
    features: pd.DataFrame, count: int, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    weights = (features["residents"] + features["workers"]).to_numpy()
    rows = rng.choice(len(features), size=count, p=weights / weights.sum())
    latitudes = features["lat"].to_numpy()[rows] + rng.uniform(
        -POINT_JITTER_DEGREES, POINT_JITTER_DEGREES, count
    )
    longitudes = features["lon"].to_numpy()[rows] + rng.uniform(
        -POINT_JITTER_DEGREES, POINT_JITTER_DEGREES, count
    )
    return latitudes.round(6), longitudes.round(6)


def competitor_brand(niche_code: str, rng: np.random.Generator) -> str | None:
    if niche_code == "pickup_point":
        return str(rng.choice(PICKUP_BRANDS))
    return None


@cache
def build_competitors(city_code: str) -> pd.DataFrame:
    city = get_city(city_code)
    features = build_hex_features(city_code)
    rng = city_rng(city, salt=1)
    rows = []
    for niche in load_niches():
        count = COMPETITOR_COUNTS[city.code][niche.code]
        latitudes, longitudes = sample_points(features, count, rng)
        for index, (latitude, longitude) in enumerate(zip(latitudes, longitudes, strict=True), start=1):
            from_mos_ru = city.code == "moscow" and niche.code == "coffee" and rng.random() < MOS_RU_SHARE
            rows.append(
                {
                    "poi_id": f"fixture-{niche.code}-{index:05d}",
                    "niche": niche.code,
                    "name": f"{COMPETITOR_TITLES[niche.code]} {index}",
                    "brand": competitor_brand(niche.code, rng),
                    "lat": float(latitude),
                    "lon": float(longitude),
                    "h3": h3.latlng_to_cell(latitude, longitude, city.h3_resolution),
                    "source": "mos_ru" if from_mos_ru else "osm",
                    "seats": int(rng.integers(10, 60)) if from_mos_ru else None,
                }
            )
    frame = pd.DataFrame(rows, columns=COMPETITOR_COLUMNS)
    frame["seats"] = frame["seats"].astype("Int64")
    return frame


def build_wages(city_code: str) -> pd.DataFrame:
    city = get_city(city_code)
    rng = city_rng(city, salt=2)
    rows = [
        {
            "profession": profession,
            "salary_p25": round(median * 0.85),
            "salary_p50": median,
            "salary_p75": round(median * 1.2),
            "vacancies_n": int(rng.integers(20, 400)),
            "collected_at": FIXTURE_COLLECTED_AT,
            "basis": "direct",
        }
        for profession, median in WAGE_MEDIANS[city.code].items()
    ]
    return pd.DataFrame(rows, columns=WAGE_COLUMNS)


@cache
def build_addresses(city_code: str) -> pd.DataFrame:
    city = get_city(city_code)
    features = build_hex_features(city_code)
    rng = city_rng(city, salt=3)
    latitudes, longitudes = sample_points(features, ADDRESSES_PER_CITY, rng)
    addresses = [
        f"{STREET_NAMES[index % len(STREET_NAMES)]}, {index // len(STREET_NAMES) + 1}"
        for index in range(ADDRESSES_PER_CITY)
    ]
    frame = pd.DataFrame(
        {
            "address": addresses,
            "lat": latitudes,
            "lon": longitudes,
            "h3": [
                h3.latlng_to_cell(latitude, longitude, city.h3_resolution)
                for latitude, longitude in zip(latitudes, longitudes, strict=True)
            ],
        }
    )
    return frame[ADDRESS_COLUMNS]


def fixture_boundary(city_code: str) -> dict:
    return h3.cells_to_geo(fixture_cells(get_city(city_code)))


def write_fixtures(city_code: str, target_dir: Path | None = None) -> Path:
    target = target_dir or processed_dir(city_code)
    target.mkdir(parents=True, exist_ok=True)
    build_hex_features(city_code).to_parquet(target / "hex_features.parquet", index=False)
    build_competitors(city_code).to_parquet(target / "competitors.parquet", index=False)
    build_wages(city_code).to_parquet(target / "wages.parquet", index=False)
    build_addresses(city_code).to_parquet(target / "addresses.parquet", index=False)
    (target / "boundary.geojson").write_text(json.dumps(fixture_boundary(city_code)), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> None:
    city_codes = [city.code for city in load_cities()]
    parser = argparse.ArgumentParser(description="Синтетические данные ГеоСтарта по схемам контракта")
    parser.add_argument("--city", required=True, choices=[*city_codes, "all"])
    arguments = parser.parse_args(argv)
    selected = city_codes if arguments.city == "all" else [arguments.city]
    for city_code in selected:
        target = write_fixtures(city_code)
        print(f"Синтетические данные города {city_code} записаны в {target}")


if __name__ == "__main__":
    main()
