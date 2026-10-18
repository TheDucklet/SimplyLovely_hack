import argparse
import csv
import hashlib
import json
import logging
import re
from difflib import SequenceMatcher
from enum import StrEnum
from pathlib import Path
from time import perf_counter

import duckdb
import numpy as np
import pandas as pd

from geostart import settings
from geostart.model.data import configure_environment
from geostart.model.demand import distances_m

RCSI_URL = "https://data.rcsi.science/data-catalog/datasets/205/"
RCSI_LICENSE = "CC BY-SA 4.0"
CHUNK_MEMORY = "512MB"
THREADS = 2
SOURCE_SAMPLE_BYTES = 65536
ADDRESS_THRESHOLD = 0.94
BRAND_THRESHOLD = 0.90
MATCH_MARGIN = 0.05
MONTHS_PER_YEAR = 12
CITIES = ("moscow", "tula")
FILTER_VERSION = 1
MAX_POINT_DISTANCE_M = 150
POINT_MARGIN_M = 30
RCSI_COLUMNS = (
    "tin",
    "year",
    "kind",
    "category",
    "org_name",
    "org_short_name",
    "activity_code_main",
    "region_iso_code",
    "region_code",
    "region",
    "settlement",
    "start_date",
    "end_date",
    "revenue",
)


class MatchStatus(StrEnum):
    EXACT = "exact"
    FUZZY = "fuzzy"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"
    UNAVAILABLE = "unavailable"


class DataSource(StrEnum):
    RCSI = "rcsi"
    GIRBO = "girbo_manual"


def source_fingerprint(path: Path) -> dict:
    stat = path.stat()
    with path.open("rb") as stream:
        header = stream.read(SOURCE_SAMPLE_BYTES)
    return {
        "filename": path.name,
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "first_64k_sha256": hashlib.sha256(header).hexdigest(),
    }


def extract_rcsi(source: Path, destination: Path) -> dict:
    fingerprint = source_fingerprint(source)
    metadata_path = destination.with_suffix(".source.json")
    if destination.is_file() and metadata_path.is_file():
        previous = json.loads(metadata_path.read_text(encoding="utf-8"))
        if previous.get("filter_version", 1) == FILTER_VERSION and all(
            previous.get(key) == value for key, value in fingerprint.items()
        ):
            return previous | {"reused": True}
    with source.open(encoding="utf-8-sig", newline="") as stream:
        first_line = stream.readline()
    delimiter = csv.Sniffer().sniff(first_line, delimiters=";,\t").delimiter
    columns = next(csv.reader([first_line], delimiter=delimiter))
    missing = set(RCSI_COLUMNS).difference(columns)
    if missing:
        raise ValueError(f"В наборе РЦНИ отсутствуют колонки {', '.join(sorted(missing))}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".pending.parquet")
    started = perf_counter()
    with duckdb.connect() as connection:
        connection.execute("SET memory_limit = ?", [CHUNK_MEMORY])
        connection.execute("SET threads = ?", [THREADS])
        connection.execute("SET temp_directory = ?", [str(destination.parent / "duckdb_tmp")])
        connection.execute("SET enable_progress_bar = false")
        connection.execute(
            """
            COPY (
                WITH selected AS (
                    SELECT tin, year, category, org_name, org_short_name, activity_code_main,
                        start_date, end_date, revenue, settlement,
                        CASE
                            WHEN region_iso_code = 'RU-MOW' OR try_cast(region_code AS INTEGER) = 77
                                THEN 'moscow'
                            WHEN (region_iso_code = 'RU-TUL' OR try_cast(region_code AS INTEGER) = 71)
                                AND lower(trim(settlement)) IN ('тула', 'г тула', 'г. тула', 'город тула')
                                THEN 'tula'
                        END AS city
                    FROM read_csv($source, delim = $delimiter, header = true, all_varchar = true)
                    WHERE kind = '1' AND trim(activity_code_main) = '56.30'
                )
                SELECT * FROM selected WHERE city IS NOT NULL
            ) TO $destination (FORMAT PARQUET, COMPRESSION ZSTD)
            """,
            {"source": str(source), "delimiter": delimiter, "destination": str(temporary)},
        )
    if source_fingerprint(source) != fingerprint:
        raise RuntimeError("Исходный CSV изменился во время чтения, повторите расчёт")
    temporary.replace(destination)
    fingerprint.update(
        seconds=perf_counter() - started,
        delimiter=delimiter,
        source=RCSI_URL,
        license=RCSI_LICENSE,
        filter_version=FILTER_VERSION,
    )
    destination.with_suffix(".source.json").write_text(
        json.dumps(fingerprint, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return fingerprint


def numeric(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(pd.StringDtype(storage="python"))
        .str.replace(r"[\s\u00a0]", "", regex=True)
        .str.replace(",", ".")
    )
    return pd.to_numeric(cleaned, errors="coerce")


def organization_years(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    frame = raw.copy()
    frame["inn"] = frame.tin.astype("string").str.strip()
    frame["year"] = pd.to_numeric(frame.year, errors="coerce")
    frame["revenue_annual_rub"] = numeric(frame.revenue)
    frame.loc[~np.isfinite(frame.revenue_annual_rub), "revenue_annual_rub"] = np.nan
    valid = (
        frame.inn.str.fullmatch(r"\d{10}").fillna(False)
        & frame.year.between(1900, 2100)
        & frame.year.mod(1).eq(0)
    )
    audit = {"raw_rows": len(frame), "invalid_identifier_or_year": int((~valid).sum())}
    frame = frame.loc[valid].copy()
    audit["unique_organizations"] = int(frame.inn.nunique())
    frame["year"] = frame.year.astype(int)
    keys = ["inn", "year", "city"]
    grouped = frame.groupby(keys, sort=False)
    counts = grouped.revenue_annual_rub.nunique().rename("revenue_versions")
    revenues = grouped.revenue_annual_rub.max().rename("revenue_value")
    latest = frame.sort_values(["end_date", "start_date"], na_position="first").drop_duplicates(
        keys, keep="last"
    )
    latest = latest.merge(counts, on=keys, validate="one_to_one").merge(
        revenues, on=keys, validate="one_to_one"
    )
    latest["revenue_annual_rub"] = latest.revenue_value.where(latest.revenue_versions.le(1))
    latest["category"] = pd.to_numeric(latest.category, errors="coerce")
    latest["revenue_month_rub"] = latest.revenue_annual_rub / MONTHS_PER_YEAR
    city_counts = latest.groupby(["inn", "year"]).city.transform("nunique")
    latest["city_year_ambiguous"] = city_counts.gt(1)
    latest["source"] = DataSource.RCSI
    latest["revenue_metric"] = "organization_income"
    latest["source_url"] = RCSI_URL
    latest["license"] = RCSI_LICENSE
    latest["name"] = latest.org_short_name.fillna(latest.org_name)
    latest["okved"] = latest.activity_code_main
    latest["address"] = pd.NA
    latest["h3"] = pd.NA
    latest["address_status"] = MatchStatus.UNAVAILABLE
    latest["chain_status"] = MatchStatus.UNAVAILABLE
    latest["points_count"] = pd.NA
    latest["points_count_source"] = pd.NA
    audit.update(
        organization_years=len(latest),
        duplicates_removed=len(frame) - len(latest),
        conflicting_revenue_years=int(latest.revenue_versions.gt(1).sum()),
        missing_revenue_years=int(latest.revenue_annual_rub.isna().sum()),
        nonpositive_revenue_years=int(latest.revenue_annual_rub.le(0).sum()),
        multiple_city_years=int(
            latest.loc[latest.city_year_ambiguous, ["inn", "year"]].drop_duplicates().shape[0]
        ),
    )
    return latest.drop(columns=["tin", "revenue", "revenue_value"]), audit


def normalized_name(value: object) -> str:
    if pd.isna(value):
        return ""
    tokens = re.findall(r"[a-zа-я0-9]+", str(value).lower().replace("ё", "е"))
    ignored = {"ооо", "ао", "пао", "зао", "оао", "общество", "ограниченной", "ответственностью", "с"}
    return " ".join(token for token in tokens if token not in ignored)


def address_parts(value: object) -> tuple[str, str]:
    if pd.isna(value):
        return "", ""
    text = str(value).lower().replace("ё", "е").strip()
    text = re.sub(r"^\s*\d{6}\s*,?", "", text)
    text = re.sub(r"(^|,)\s*(?:россия|(?:г\.?\s*|город\s+)?москва)\s*(?=,|$)", "", text)
    text = text.strip(" ,")
    text = re.sub(r"\b(?:дом|д)\.?\s*(?=\d)", ",", text)
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if len(parts) < 2:
        found = re.search(r"\s+(\d+[а-яa-z]?(?:[/\-]\d+)?(?:\s*[кс]\s*\d+)*)$", text)
        if found is None:
            return "", ""
        parts = [text[: found.start()], found.group(1)]
    street = parts[0]
    replacements = {
        r"\bул\b\.?": "улица",
        r"\bпр-т\b\.?": "проспект",
        r"\bпер\b\.?": "переулок",
        r"\bпр-д\b\.?": "проезд",
        r"\bбул\b\.?": "бульвар",
        r"\bнаб\b\.?": "набережная",
        r"\bпл\b\.?": "площадь",
        r"\bш\b\.?": "шоссе",
    }
    for pattern, replacement in replacements.items():
        street = re.sub(pattern, replacement, street)
    house = " ".join(parts[1:])
    house = re.sub(r"\b(?:корпус|корп)\b\.?", "к", house)
    house = re.sub(r"\b(?:строение|стр)\b\.?", "с", house)
    house = re.sub(r"[^а-яa-z0-9/\-]", "", house)
    return " ".join(sorted(re.findall(r"[а-яa-z0-9]+", street))), house


def address_match(address: object, addresses: pd.DataFrame) -> dict:
    street, house = address_parts(address)
    empty = {"h3": None, "address_status": MatchStatus.UNMATCHED, "address_score": None}
    if not street or not house:
        return empty
    selected = addresses.loc[addresses.house_key.eq(house)].copy()
    if selected.empty:
        return empty
    exact = selected.loc[selected.street_key.eq(street)]
    if not exact.empty:
        selected = exact.copy()
    selected["score"] = selected.street_key.map(lambda item: SequenceMatcher(None, street, item).ratio())
    ranked = selected.sort_values("score", ascending=False)
    best = float(ranked.iloc[0].score)
    if best < ADDRESS_THRESHOLD:
        return empty | {"address_score": best}
    top = ranked.loc[ranked.score.ge(best - MATCH_MARGIN)]
    if top.h3.nunique() != 1:
        return empty | {"address_status": MatchStatus.AMBIGUOUS, "address_score": best}
    row = ranked.iloc[0]
    return {
        "h3": row.h3,
        "address_status": MatchStatus.EXACT if best == 1 else MatchStatus.FUZZY,
        "address_score": best,
        "matched_address": row.address,
        "lat": float(row.lat),
        "lon": float(row.lon),
    }


def brand_match(name: object, point_names: dict[str, pd.DataFrame], location: dict) -> dict:
    query = normalized_name(name)
    empty = {"chain_status": MatchStatus.UNMATCHED, "mos_ru_poi_id": None, "chain_candidates": 0}
    if len(query) < 3 or query in {"кофе", "кофейня", "кафе", "coffee"}:
        return empty
    ranking = sorted(
        ((SequenceMatcher(None, query, candidate).ratio(), candidate) for candidate in point_names),
        reverse=True,
    )
    if query in point_names:
        ranking = [(1.0, query)]
    if not ranking or ranking[0][0] < BRAND_THRESHOLD:
        return empty
    score, matched = ranking[0]
    if len(ranking) > 1 and score - ranking[1][0] < MATCH_MARGIN:
        return empty | {"chain_status": MatchStatus.AMBIGUOUS, "chain_score": score}
    points = point_names[matched].drop_duplicates("poi_id")
    result = empty | {
        "chain_status": MatchStatus.EXACT if score == 1 else MatchStatus.FUZZY,
        "chain_name": matched,
        "chain_score": score,
        "chain_candidates": len(points),
    }
    if not location.get("h3"):
        return result
    distances = distances_m(
        np.tile([location["lat"], location["lon"]], (len(points), 1)), points[["lat", "lon"]].to_numpy()
    )
    order = np.argsort(distances)
    if distances[order[0]] > MAX_POINT_DISTANCE_M:
        return result
    if len(order) > 1 and distances[order[1]] - distances[order[0]] < POINT_MARGIN_M:
        return result | {"point_ambiguous": True}
    row = points.iloc[order[0]]
    return result | {
        "mos_ru_poi_id": row.poi_id,
        "mos_ru_name": row["name"],
        "mos_ru_seats": row.seats,
        "point_distance_m": float(distances[order[0]]),
    }


def read_girbo(path: Path, revenue_unit: str | None = None) -> pd.DataFrame:
    frame = pd.read_csv(path, sep=None, engine="python", dtype="string")
    aliases = {
        "инн": "inn",
        "tin": "inn",
        "название": "name",
        "наименование": "name",
        "оквэд": "okved",
        "адрес": "address",
        "сеть": "chain_name",
        "название_сети": "chain_name",
        "выручка_2025_руб": "revenue_2025_rub",
        "число_точек": "points_count",
        "источник_числа_точек": "points_count_source",
        "источник": "source_url",
    }
    frame.columns = [aliases.get(column.strip().lower(), column.strip().lower()) for column in frame.columns]
    if frame.columns.duplicated().any():
        raise ValueError("В таблице Ивана повторяются колонки после сопоставления заголовков")
    required = {"inn", "name", "okved", "address"}
    if not required.issubset(frame.columns):
        raise ValueError("Таблица Ивана должна содержать inn, name, okved, address и годовую выручку 2025")
    if "revenue_2025_rub" in frame:
        revenue = numeric(frame.revenue_2025_rub)
    elif "revenue_2025_thousand_rub" in frame:
        revenue = numeric(frame.revenue_2025_thousand_rub) * 1000
    elif "revenue_2025" in frame and revenue_unit is not None:
        revenue = numeric(frame.revenue_2025) * (1000 if revenue_unit == "thousand_rub" else 1)
    else:
        raise ValueError(
            "Укажите revenue_2025_rub либо revenue_2025_thousand_rub, для revenue_2025 задайте единицу"
        )
    if not frame.inn.str.fullmatch(r"\d{10}").fillna(False).all():
        raise ValueError("Для юридических лиц в таблице Ивана нужен ИНН из 10 цифр")
    if "year" in frame and not numeric(frame.year).eq(2025).all():
        raise ValueError("В таблице Ивана ожидается выручка 2025 года")
    frame["revenue_annual_rub"] = revenue.where(np.isfinite(revenue))
    frame["revenue_month_rub"] = frame.revenue_annual_rub / MONTHS_PER_YEAR
    frame["city"] = "moscow"
    frame["year"] = 2025
    frame["source"] = DataSource.GIRBO
    frame["revenue_metric"] = "sales_revenue"
    frame["license"] = pd.NA
    frame["h3"] = pd.NA
    frame["points_count"] = frame.get("points_count", pd.Series(pd.NA, index=frame.index))
    frame["points_count_source"] = frame.get("points_count_source", pd.Series(pd.NA, index=frame.index))
    return frame


def link_girbo(frame: pd.DataFrame, addresses: pd.DataFrame, competitors: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.assign(address_status=pd.Series(dtype="string"), chain_status=pd.Series(dtype="string"))
    addresses = addresses.copy()
    keys = addresses.address.map(address_parts)
    addresses["street_key"] = keys.map(lambda item: item[0])
    addresses["house_key"] = keys.map(lambda item: item[1])
    selected = competitors.loc[competitors.source.eq("mos_ru") & competitors.niche.eq("coffee")].copy()
    point_names = {}
    for column in ("name", "brand"):
        for key, points in selected.groupby(selected[column].map(normalized_name)):
            if key:
                point_names[key] = pd.concat([point_names.get(key, selected.iloc[:0]), points])
    rows = []
    for record in frame.to_dict("records"):
        location = address_match(record["address"], addresses)
        name = record.get("chain_name")
        if name is None or pd.isna(name) or not str(name).strip():
            name = record["name"]
        rows.append(record | location | brand_match(name, point_names, location))
    return pd.DataFrame(rows)


def apply_point_counts(frame: pd.DataFrame, counts_path: Path | None) -> pd.DataFrame:
    result = frame.copy()
    if counts_path is not None and counts_path.is_file():
        counts = pd.read_csv(counts_path, dtype="string")
        keys = ["inn", "city", "year"]
        if not {*keys, "points_count", "points_count_source"}.issubset(counts.columns):
            raise ValueError(
                "Подтверждения числа точек требуют inn, city, year, points_count, points_count_source"
            )
        counts["year"] = pd.to_numeric(counts.year, errors="raise").astype(int)
        if counts.duplicated(keys).any():
            raise ValueError("В подтверждениях числа точек повторяются ИНН, город и год")
        if counts.groupby(["inn", "year"]).points_count.nunique().gt(1).any():
            raise ValueError("Число точек всей организации за один год не должно различаться по городам")
        counts = counts[[*keys, "points_count", "points_count_source"]]
        result = result.merge(counts, on=keys, how="left", suffixes=("", "_verified"), validate="many_to_one")
        for column in ("points_count", "points_count_source"):
            both = result[column].notna() & result[f"{column}_verified"].notna()
            if (
                column == "points_count"
                and (
                    numeric(result.loc[both, column]) != numeric(result.loc[both, f"{column}_verified"])
                ).any()
            ):
                raise ValueError("Противоречивое число точек в таблице Ивана и подтверждениях")
            result[column] = result[column].combine_first(result[f"{column}_verified"])
            result = result.drop(columns=f"{column}_verified")
    numbers = numeric(result.points_count)
    invalid = result.points_count.notna() & (numbers.isna() | numbers.le(0) | numbers.mod(1).ne(0))
    if invalid.any():
        raise ValueError("Число точек должно быть положительным целым")
    result["points_count"] = numbers.astype("Int64")
    sources = result.points_count_source.astype("string").str.strip().replace("", pd.NA)
    result["single_location_verified"] = result.points_count.eq(1).fillna(False) & sources.notna()
    return result


def quantile_row(frame: pd.DataFrame, city: str, year: int, verified: bool) -> dict:
    values = frame.revenue_annual_rub.dropna().to_numpy(dtype=float)
    quantiles = np.quantile(values, [0.1, 0.5, 0.9]).tolist() if len(values) else [None] * 3
    return {
        "city": city,
        "year": year,
        "scope": "verified_single_location" if verified else "organization_background",
        "organizations": len(frame),
        **{f"annual_p{percent}": value for percent, value in zip((10, 50, 90), quantiles, strict=True)},
        **{
            f"month_p{percent}": None if value is None else value / MONTHS_PER_YEAR
            for percent, value in zip((10, 50, 90), quantiles, strict=True)
        },
    }


def export_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    columns = (
        "inn",
        "name",
        "okved",
        "city",
        "year",
        "category",
        "revenue_annual_rub",
        "revenue_month_rub",
        "revenue_metric",
        "source",
        "source_url",
        "license",
        "address",
        "matched_address",
        "h3",
        "address_status",
        "address_score",
        "chain_status",
        "chain_name",
        "chain_score",
        "chain_candidates",
        "mos_ru_poi_id",
        "mos_ru_name",
        "mos_ru_seats",
        "point_distance_m",
        "points_count",
        "points_count_source",
        "single_location_verified",
    )
    for column in columns:
        if column not in frame:
            frame[column] = pd.NA
    frame["point_calibration_candidate"] = (
        frame.single_location_verified.fillna(False)
        & frame.h3.notna()
        & frame.mos_ru_poi_id.notna()
        & frame.revenue_annual_rub.gt(0)
    )
    if not frame.empty:
        ambiguous = frame.groupby(["inn", "year"]).h3.transform("nunique").gt(1)
        frame.loc[ambiguous, "point_calibration_candidate"] = False
    for column in ("inn", "h3", "mos_ru_poi_id", "address_status", "chain_status", "source"):
        frame[column] = frame[column].astype("string")
    return frame[[*columns, "point_calibration_candidate"]].reset_index(drop=True)


def build_calibration(
    rcsi_path: Path | None,
    girbo_path: Path,
    destination: Path,
    counts_path: Path | None = None,
    revenue_unit: str | None = None,
) -> dict:
    if (rcsi_path is None or not rcsi_path.is_file()) and not girbo_path.is_file():
        raise FileNotFoundError("Нет ни локального panel.csv РЦНИ, ни таблицы Ивана, укажите путь к данным")
    destination.mkdir(parents=True, exist_ok=True)
    summary = {"girbo_present": girbo_path.is_file(), "sources": [], "distributions": []}
    summary["point_counts_present"] = counts_path is not None and counts_path.is_file()
    attribution = {
        "title": "Реестр субъектов МСП 2016-2024 с доходами, расходами и численностью работников",
        "publisher": "Каталог данных РЦНИ, платформа ИНИД",
        "source": RCSI_URL,
        "license": RCSI_LICENSE,
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "changes": "Отбор организаций по городам и ОКВЭД, удаление повторов, расчёт распределений",
    }
    if rcsi_path is not None and rcsi_path.is_file():
        (destination / "rcsi_attribution.json").write_text(
            json.dumps(attribution, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    all_years = pd.DataFrame()
    if rcsi_path is not None and rcsi_path.is_file():
        extracted = destination / "rcsi_coffee_candidates.parquet"
        summary["sources"].append(extract_rcsi(rcsi_path, extracted))
        all_years, summary["rcsi_audit"] = organization_years(pd.read_parquet(extracted))
        all_years = apply_point_counts(all_years, counts_path)
        all_years.to_parquet(destination / "rcsi_organization_years.parquet", index=False)
    girbo = pd.DataFrame()
    if girbo_path.is_file():
        girbo = read_girbo(girbo_path, revenue_unit)
        directory = settings.processed_dir("moscow")
        girbo = link_girbo(
            girbo,
            pd.read_parquet(directory / "addresses.parquet"),
            pd.read_parquet(directory / "competitors.parquet"),
        )
        girbo = apply_point_counts(girbo, counts_path)
        export_columns(girbo).to_parquet(destination / "girbo_address_links.parquet", index=False)
    summary["girbo_coverage"] = {
        "rows": len(girbo),
        "address_matched": 0 if girbo.empty else int(girbo.h3.notna().sum()),
        "address_match_share": None if girbo.empty else float(girbo.h3.notna().mean()),
        "point_matched": 0 if girbo.empty else int(export_columns(girbo).mos_ru_poi_id.notna().sum()),
    }
    for city in CITIES:
        eligible = (
            all_years.iloc[:0]
            if all_years.empty
            else all_years.loc[
                all_years.city.eq(city)
                & all_years.category.isin([1, 2])
                & all_years.revenue_annual_rub.gt(0)
                & ~all_years.city_year_ambiguous
            ]
        )
        for year, group in eligible.groupby("year") if not eligible.empty else []:
            summary["distributions"].append(quantile_row(group, city, int(year), False))
            summary["distributions"].append(
                quantile_row(group.loc[group.single_location_verified], city, int(year), True)
            )
        latest = eligible.loc[eligible.year.eq(eligible.year.max())] if not eligible.empty else eligible
        manual = girbo.loc[girbo.city.eq(city)] if not girbo.empty else girbo
        sample = pd.concat([latest, manual], ignore_index=True)
        export_columns(sample).to_parquet(destination / f"{city}_coffee.parquet", index=False)
    pd.DataFrame(summary["distributions"]).to_parquet(
        destination / "revenue_distributions.parquet", index=False
    )
    (destination / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    return summary


def plot_distributions(directory: Path, target: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    figure, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True, layout="constrained")
    for axis, city, label in zip(axes, CITIES, ("Москва", "Тула"), strict=True):
        frame = pd.read_parquet(directory / f"{city}_coffee.parquet")
        frame = frame.loc[frame.source.eq(DataSource.RCSI)]
        values = np.sort(frame.revenue_month_rub.to_numpy(dtype=float)) / 1_000_000
        if len(values):
            axis.step(values, np.arange(1, len(values) + 1) / len(values), where="post")
            axis.set_xscale("log")
        year = "нет данных" if frame.empty else str(int(frame.year.max()))
        axis.set_title(f"{label}, {year}, n = {len(values)}")
        axis.set_xlabel("Месячный эквивалент дохода, млн ₽")
        axis.grid(alpha=0.25)
    axes[0].set_ylabel("Доля организаций")
    figure.suptitle("ОКВЭД 56.30, число торговых точек не подтверждено")
    target.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        target,
        dpi=160,
        metadata={"Source": RCSI_URL, "License": RCSI_LICENSE, "Publisher": "РЦНИ, платформа ИНИД"},
    )
    plt.close(figure)


def main(argv: list[str] | None = None) -> None:
    configure_environment()
    parser = argparse.ArgumentParser(description="Локальная выборка выручки кофеен R-R1")
    parser.add_argument("--rcsi-file", type=Path, default=settings.data_dir() / "raw/rcsi/panel.csv")
    parser.add_argument(
        "--girbo-file", type=Path, default=settings.research_dir() / "calibration/girbo_coffee.csv"
    )
    parser.add_argument(
        "--point-counts", type=Path, default=settings.research_dir() / "calibration/point_counts.csv"
    )
    parser.add_argument("--output-dir", type=Path, default=settings.data_dir() / "calibration")
    parser.add_argument("--girbo-revenue-unit", choices=("rub", "thousand_rub"))
    parser.add_argument("--plot", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = build_calibration(
        args.rcsi_file, args.girbo_file, args.output_dir, args.point_counts, args.girbo_revenue_unit
    )
    if args.plot is not None:
        plot_distributions(args.output_dir, args.plot)
    logging.info(
        "Выборка сохранена в %s, таблица Ивана %s",
        args.output_dir,
        "есть" if result["girbo_present"] else "отсутствует",
    )


if __name__ == "__main__":
    main()
