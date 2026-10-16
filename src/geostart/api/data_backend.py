from functools import lru_cache
from pathlib import Path

import pandas as pd

from geostart.config import CityConfig
from geostart.model import evaluate_location
from geostart.schemas import AddressMatch, Competitor, HexesResponse, HexScore, LocationReport, ReportRequest
from geostart.settings import data_dir, processed_dir

SEARCH_LIMIT = 10
UNKNOWN_DATA_VERSION = "нет данных"
PARQUET_CACHE_SIZE = 32


class DataNotReadyError(LookupError):
    pass


@lru_cache(maxsize=PARQUET_CACHE_SIZE)
def read_parquet_version(path: str, modified_ns: int) -> pd.DataFrame:
    return pd.read_parquet(path)


def read_parquet(path: Path, missing_message: str) -> pd.DataFrame:
    if not path.is_file():
        raise DataNotReadyError(missing_message)
    return read_parquet_version(str(path), path.stat().st_mtime_ns)


def scores_path(city_code: str, niche_code: str) -> Path:
    return data_dir() / "scores" / f"{city_code}_{niche_code}.parquet"


def processed_file(city_code: str, name: str) -> pd.DataFrame:
    return read_parquet(
        processed_dir(city_code) / name,
        f"Данные города {city_code} не загружены, запустите uv run python -m geostart.pipeline run "
        f"--city {city_code} или распакуйте архив данных",
    )


def city_data_version(city_code: str) -> str:
    try:
        wages = processed_file(city_code, "wages.parquet")
    except DataNotReadyError:
        return UNKNOWN_DATA_VERSION
    if wages.empty:
        return UNKNOWN_DATA_VERSION
    return pd.to_datetime(wages["collected_at"]).max().date().isoformat()


def latest_data_version(city_codes: list[str]) -> str:
    versions = [
        version for code in city_codes if (version := city_data_version(code)) != UNKNOWN_DATA_VERSION
    ]
    return max(versions) if versions else UNKNOWN_DATA_VERSION


def optional_number(value: float) -> float | None:
    return None if pd.isna(value) else float(value)


def optional_text(value: object) -> str | None:
    return None if pd.isna(value) else str(value)


def data_hexes(city_code: str, niche_code: str) -> HexesResponse:
    scores = read_parquet(
        scores_path(city_code, niche_code),
        f"Город {city_code} ещё не рассчитан для ниши {niche_code}, запустите "
        f"uv run python -m geostart.model score --city {city_code} --niche {niche_code}",
    )
    items = [
        HexScore(
            h3=row.h3,
            revenue_p50=round(float(row.revenue_p50)),
            payback_months_p50=optional_number(row.payback_months_p50),
            risk_level=row.risk_level,
            competitors_500m=int(row.competitors_500m),
        )
        for row in scores.itertuples(index=False)
    ]
    return HexesResponse(
        city=city_code, niche=niche_code, data_version=city_data_version(city_code), items=items
    )


def data_competitors(city_code: str, niche_code: str) -> list[Competitor]:
    competitors = processed_file(city_code, "competitors.parquet")
    selected = competitors[competitors["niche"] == niche_code]
    return [
        Competitor(
            name=row.name,
            brand=optional_text(row.brand),
            lat=float(row.lat),
            lon=float(row.lon),
            source=row.source,
        )
        for row in selected.itertuples(index=False)
    ]


def normalized(text: pd.Series | str) -> pd.Series | str:
    if isinstance(text, str):
        return text.lower().replace("ё", "е")
    return text.str.lower().str.replace("ё", "е", regex=False)


def data_search(city_code: str, query: str) -> list[AddressMatch]:
    addresses = processed_file(city_code, "addresses.parquet")
    tokens = [token.strip(",.") for token in normalized(query).split() if token.strip(",.")]
    if not tokens:
        return []
    haystack = normalized(addresses["address"])
    mask = pd.Series(True, index=addresses.index)
    for token in tokens:
        mask &= haystack.str.contains(token, regex=False)
    matched_text = haystack[mask]
    house_numbers = matched_text.str.rsplit(", ", n=1).str[-1].str.split().str[0]
    matches = addresses[mask].assign(
        exact_house=house_numbers.isin(tokens),
        starts=matched_text.str.startswith(tokens[0]),
    )
    matches = matches.sort_values(["exact_house", "starts", "address"], ascending=[False, False, True]).head(
        SEARCH_LIMIT
    )
    return [
        AddressMatch(address=row.address, lat=row.lat, lon=row.lon) for row in matches.itertuples(index=False)
    ]


def data_report(city: CityConfig, request: ReportRequest) -> LocationReport:
    return evaluate_location(
        city=city.code,
        niche=request.niche,
        lat=request.lat,
        lon=request.lon,
        area_m2=request.area_m2,
        rent_rub_m2_month=request.rent_rub_m2_month,
    )
