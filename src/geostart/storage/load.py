import logging
from pathlib import Path

import pandas as pd
import psycopg

from geostart.config import get_city, load_niches
from geostart.settings import REPOSITORY_ROOT, data_dir, processed_dir
from geostart.storage.connection import DatabaseRole, connect

logger = logging.getLogger(__name__)

SCHEMA_DIR = REPOSITORY_ROOT / "sql"
HEX_COLUMNS = [
    "city",
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
COMPETITOR_COLUMNS = ["city", "poi_id", "niche", "name", "brand", "lat", "lon", "h3", "source", "seats"]
ADDRESS_COLUMNS = ["city", "address", "address_search", "lat", "lon", "h3"]
SCORE_COLUMNS = [
    "city",
    "niche",
    "h3",
    "revenue_p10",
    "revenue_p50",
    "revenue_p90",
    "profit_p50",
    "payback_months_p50",
    "risk_level",
    "competitors_500m",
]
CITY_TABLES = ("geo.hex_features", "geo.competitors", "geo.addresses", "geo.scores", "geo.data_versions")


def apply_schema(connection: psycopg.Connection) -> list[str]:
    applied = []
    for path in sorted(SCHEMA_DIR.glob("*.sql")):
        connection.execute(path.read_text(encoding="utf-8"))
        applied.append(path.name)
    return applied


def search_text(addresses: pd.Series) -> pd.Series:
    return addresses.str.lower().str.replace("ё", "е", regex=False)


def database_value(value: object) -> object:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def copy_rows(connection: psycopg.Connection, table: str, columns: list[str], frame: pd.DataFrame) -> int:
    with (
        connection.cursor() as cursor,
        cursor.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as copy,
    ):
        for row in frame[columns].itertuples(index=False, name=None):
            copy.write_row([database_value(value) for value in row])
    return len(frame)


def city_frames(city_code: str) -> dict[str, pd.DataFrame]:
    directory = processed_dir(city_code)
    hexes = pd.read_parquet(directory / "hex_features.parquet").assign(city=city_code)
    competitors = pd.read_parquet(directory / "competitors.parquet").assign(city=city_code)
    addresses = pd.read_parquet(directory / "addresses.parquet").assign(city=city_code)
    addresses = addresses.drop_duplicates("address").assign(
        address_search=lambda frame: search_text(frame["address"])
    )
    scores = []
    for niche in load_niches():
        path = data_dir() / "scores" / f"{city_code}_{niche.code}.parquet"
        if path.is_file():
            scores.append(pd.read_parquet(path).assign(city=city_code, niche=niche.code))
        else:
            logger.warning(
                "Нет расчёта %s для ниши %s, карта ниши в базе будет пустой", city_code, niche.code
            )
    wages = pd.read_parquet(directory / "wages.parquet")
    return {
        "hexes": hexes,
        "competitors": competitors,
        "addresses": addresses,
        "scores": pd.concat(scores, ignore_index=True) if scores else pd.DataFrame(columns=SCORE_COLUMNS),
        "data_version": pd.DataFrame(
            {
                "city": [city_code],
                "data_version": [pd.to_datetime(wages["collected_at"]).max().date().isoformat()],
            }
        ),
    }


def load_city(connection: psycopg.Connection, city_code: str) -> dict[str, int]:
    get_city(city_code)
    frames = city_frames(city_code)
    for table in CITY_TABLES:
        connection.execute(f"DELETE FROM {table} WHERE city = %s", (city_code,))
    return {
        "hex_features": copy_rows(connection, "geo.hex_features", HEX_COLUMNS, frames["hexes"]),
        "competitors": copy_rows(connection, "geo.competitors", COMPETITOR_COLUMNS, frames["competitors"]),
        "addresses": copy_rows(connection, "geo.addresses", ADDRESS_COLUMNS, frames["addresses"]),
        "scores": copy_rows(connection, "geo.scores", SCORE_COLUMNS, frames["scores"]),
        "data_versions": copy_rows(
            connection, "geo.data_versions", ["city", "data_version"], frames["data_version"]
        ),
    }


def migrate() -> list[str]:
    with connect(DatabaseRole.LOADER) as connection:
        return apply_schema(connection)


def load_cities_into_database(city_codes: list[str]) -> dict[str, dict[str, int]]:
    results = {}
    with connect(DatabaseRole.LOADER) as connection:
        apply_schema(connection)
        for city_code in city_codes:
            if not (processed_dir(city_code) / "hex_features.parquet").is_file():
                raise FileNotFoundError(
                    f"Нет данных города {city_code} в {processed_dir(city_code)}, запустите конвейер"
                )
            with connection.transaction():
                results[city_code] = load_city(connection, city_code)
    return results


def schema_files() -> list[Path]:
    return sorted(SCHEMA_DIR.glob("*.sql"))
