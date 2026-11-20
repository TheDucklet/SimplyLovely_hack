import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd

from geostart.config import load_cities, load_niches
from geostart.pipeline import geometry

PROCESSED_FILES = (
    "hex_features.parquet",
    "competitors.parquet",
    "addresses.parquet",
    "wages.parquet",
    "boundary.geojson",
)
RISK_LEVELS = ("low", "medium", "high")
HASH_CHUNK = 1 << 20


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def number(value: object) -> float | None:
    return None if pd.isna(value) else round(float(value), 2)


def city_summary(folder: Path, niches: list[str]) -> dict:
    hexes = pd.read_parquet(folder / "hex_features.parquet")
    competitors = pd.read_parquet(folder / "competitors.parquet")
    summary = {
        "cells": len(hexes),
        "residents": round(float(hexes["residents"].sum())),
        "workers": round(float(hexes["workers"].sum())),
        "competitors": {niche: int((competitors["niche"] == niche).sum()) for niche in niches},
    }
    if (folder / "addresses.parquet").exists():
        summary["addresses"] = len(pd.read_parquet(folder / "addresses.parquet", columns=["h3"]))
    if (folder / "wages.parquet").exists():
        wages = pd.read_parquet(folder / "wages.parquet")
        summary["wage_rows"] = len(wages)
        collected = pd.to_datetime(wages["collected_at"]).max() if len(wages) else None
        summary["wages_collected_at"] = None if collected is None else collected.date().isoformat()
    if (folder / "boundary.geojson").exists():
        area = gpd.read_file(folder / "boundary.geojson").to_crs(geometry.METRIC_CRS).area.sum()
        summary["boundary_area_km2"] = round(float(area) / 1e6, 1)
    return summary


def score_summary(path: Path) -> dict:
    scores = pd.read_parquet(path)
    risk = scores["risk_level"].value_counts(normalize=True)
    return {
        "cells": len(scores),
        "revenue_p50_median": number(scores["revenue_p50"].median()),
        "revenue_p50_p90": number(scores["revenue_p50"].quantile(0.9)),
        "profit_p50_median": number(scores["profit_p50"].median()),
        "payback_months_p50_median": number(scores["payback_months_p50"].median()),
        "risk_share": {level: round(float(risk.get(level, 0.0)), 4) for level in RISK_LEVELS},
    }


def data_files(root: Path) -> list[Path]:
    patterns = ["processed/*/*", "scores/*.parquet", "basemap/*.pmtiles"]
    return sorted(path for pattern in patterns for path in root.glob(pattern) if path.is_file())


def build_manifest(root: Path) -> dict:
    niches = [niche.code for niche in load_niches()]
    cities = {}
    scores = {}
    for city in load_cities():
        folder = root / "processed" / city.code
        if (folder / "hex_features.parquet").exists():
            cities[city.code] = city_summary(folder, niches)
        for niche in niches:
            path = root / "scores" / f"{city.code}_{niche}.parquet"
            if path.exists():
                scores[f"{city.code}/{niche}"] = score_summary(path)
    files = {path.relative_to(root).as_posix(): file_hash(path) for path in data_files(root)}
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:8]
    created = datetime.now(UTC)
    return {
        "version": f"{created.date().isoformat()}.{fingerprint}",
        "created_at": created.isoformat(timespec="seconds"),
        "cities": cities,
        "scores": scores,
        "files": files,
    }


def write_manifest(manifest: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
