import json
import zipfile
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from pydantic import BaseModel

from geostart.pipeline import geometry

DOWNLOAD_TIMEOUT_SECONDS = 120
DUPLICATE_RADIUS_M = 75.0
NET_OBJECT_FLAG = "да"
KEPT_FIELDS = (
    "global_id",
    "Name",
    "IsNetObject",
    "OperatingCompany",
    "TypeObject",
    "SeatsCount",
    "Longitude_WGS84",
    "Latitude_WGS84",
)
CATERING_COLUMNS = ["poi_id", "name", "brand", "object_type", "seats", "lat", "lon"]


class MosRuDataset(BaseModel):
    dataset_id: int
    url: str
    file: str
    date: date
    page: str


def ensure_dataset(dataset: MosRuDataset, raw_dir: Path) -> Path:
    path = raw_dir / dataset.file
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(dataset.url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()
    partial = path.with_suffix(".part")
    partial.write_bytes(response.content)
    partial.rename(path)
    return path


def read_records(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as archive:
        member = next(name for name in archive.namelist() if name.endswith(".json"))
        records = json.loads(archive.read(member).decode("utf-8-sig"))
    return [{field: record.get(field) for field in KEPT_FIELDS} for record in records]


def catering_frame(records: list[dict]) -> pd.DataFrame:
    raw = pd.DataFrame(records, columns=list(KEPT_FIELDS)).drop_duplicates("global_id")
    is_net = raw["IsNetObject"].fillna("").str.strip().str.lower().eq(NET_OBJECT_FLAG)
    company = raw["OperatingCompany"].fillna("").str.strip()
    frame = pd.DataFrame(
        {
            "poi_id": "mos_ru:" + raw["global_id"].astype(str),
            "name": raw["Name"].fillna("").str.strip(),
            "brand": company.astype(object).where(is_net & company.ne(""), None),
            "object_type": raw["TypeObject"].fillna("").str.strip(),
            "seats": pd.to_numeric(raw["SeatsCount"], errors="coerce").astype("Int64"),
            "lat": pd.to_numeric(raw["Latitude_WGS84"], errors="coerce"),
            "lon": pd.to_numeric(raw["Longitude_WGS84"], errors="coerce"),
        }
    )
    return frame.dropna(subset=["lat", "lon"]).reset_index(drop=True)[CATERING_COLUMNS]


def select_by_name(catering: pd.DataFrame, pattern: str) -> pd.DataFrame:
    return catering[catering["name"].str.contains(pattern, regex=True)].reset_index(drop=True)


def has_neighbour(points: pd.DataFrame, others: pd.DataFrame, radius_m: float) -> np.ndarray:
    if points.empty or others.empty:
        return np.zeros(len(points), dtype=bool)
    left = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(points["lon"], points["lat"]), crs=geometry.GEOGRAPHIC_CRS
    ).to_crs(geometry.METRIC_CRS)
    right = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(others["lon"], others["lat"]), crs=geometry.GEOGRAPHIC_CRS
    ).to_crs(geometry.METRIC_CRS)
    joined = gpd.sjoin_nearest(left, right, how="left", max_distance=radius_m)
    return (
        joined.groupby(level=0)["index_right"].count().reindex(range(len(points)), fill_value=0).to_numpy()
        > 0
    )


def merge_competitors(
    osm: pd.DataFrame, official: pd.DataFrame, radius_m: float = DUPLICATE_RADIUS_M
) -> pd.DataFrame:
    osm = osm.reset_index(drop=True)
    duplicates = has_neighbour(osm, official, radius_m)
    return pd.concat([official, osm[~duplicates]], ignore_index=True)
