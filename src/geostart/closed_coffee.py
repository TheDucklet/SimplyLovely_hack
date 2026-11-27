import json
import re
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import h3
import numpy as np
import pandas as pd

COFFEE_PATTERN = re.compile(r"коф|coffee|cofe|cofix|дабб|дабл|дринкит|шоколадниц|кофеман|skuratov", re.I)
MATCH_RADIUS_M = 75.0
SOURCE_FIELDS = {
    "global_id": ("global_id", "Global ID"),
    "name": ("Name", "name"),
    "lat": ("Latitude in WGS-84", "latitude", "lat"),
    "lon": ("Longitude in WGS-84", "longitude", "lon"),
}


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".zip":
        with ZipFile(path) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith((".csv", ".xlsx"))]
            if len(members) != 1:
                raise ValueError(f"В архиве должен быть один CSV или XLSX: {path}")
            member = members[0]
            data = BytesIO(archive.read(member))
            return read_member(data, member)
    return read_member(path, path.name)


def read_member(source: BytesIO | Path, name: str) -> pd.DataFrame:
    if name.lower().endswith(".csv"):
        frame = pd.read_csv(source, sep=None, engine="python", encoding="utf-8-sig")
        if "global_id" in frame.columns and frame["global_id"].astype(str).eq("global_id").any():
            frame = frame.loc[~frame["global_id"].astype(str).eq("global_id")]
        return frame
    return pd.read_excel(source)


def choose_column(frame: pd.DataFrame, names: tuple[str, ...]) -> str:
    for name in names:
        if name in frame.columns:
            return name
    raise ValueError(f"Не найдено поле {names}")


def normalize_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    columns = {key: choose_column(frame, names) for key, names in SOURCE_FIELDS.items()}
    result = frame[[columns[key] for key in SOURCE_FIELDS]].copy()
    result.columns = list(SOURCE_FIELDS)
    result["global_id"] = result["global_id"].astype(str).str.replace(r"\.0$", "", regex=True)
    result["name"] = result["name"].fillna("").astype(str)
    result["lat"] = pd.to_numeric(result["lat"], errors="coerce")
    result["lon"] = pd.to_numeric(result["lon"], errors="coerce")
    result = result.dropna(subset=["lat", "lon"]).drop_duplicates("global_id")
    return result.loc[result["name"].str.contains(COFFEE_PATTERN, na=False)].reset_index(drop=True)


def nearest_distances(points: pd.DataFrame, current: pd.DataFrame) -> np.ndarray:
    if points.empty or current.empty:
        return np.full(len(points), np.inf)
    current_lat = current["lat"].to_numpy()
    current_lon = current["lon"].to_numpy()
    distances = []
    earth_radius_m = 111320.0
    for row in points.itertuples():
        delta_lat = (current_lat - row.lat) * earth_radius_m
        delta_lon = (current_lon - row.lon) * earth_radius_m * np.cos(np.deg2rad(row.lat))
        distances.append(np.sqrt(delta_lat**2 + delta_lon**2).min())
    return np.asarray(distances)


def classify_points(historical: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    result = historical.copy()
    current_ids = set(current["global_id"])
    missing = ~result["global_id"].isin(current_ids)
    result["class"] = np.where(missing, "missing", "working")
    result["nearest_current_m"] = np.nan
    result.loc[missing, "nearest_current_m"] = nearest_distances(result.loc[missing], current)
    result.loc[missing & (result["nearest_current_m"] <= MATCH_RADIUS_M), "class"] = "uncertain"
    result.loc[missing & (result["nearest_current_m"] > MATCH_RADIUS_M), "class"] = "closed"
    return result


def attach_scores(points: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    result = points.copy()
    result["h3"] = [
        h3.latlng_to_cell(lat, lon, 9) for lat, lon in zip(result["lat"], result["lon"], strict=True)
    ]
    return result.merge(scores, on="h3", how="left")


def numeric_or_none(value: object) -> float | None:
    return None if pd.isna(value) else float(value)


def summarize(points: pd.DataFrame) -> dict[str, object]:
    scored = points.dropna(subset=["revenue_p50"]).copy()
    risk_counts = {str(key): int(value) for key, value in scored["risk_level"].value_counts().items()}
    return {
        "points": len(points),
        "scored_points": len(scored),
        "coverage": float(len(scored) / len(points)) if len(points) else 0.0,
        "revenue_p10": numeric_or_none(scored["revenue_p50"].quantile(0.1)) if len(scored) else None,
        "revenue_p50": numeric_or_none(scored["revenue_p50"].median()) if len(scored) else None,
        "revenue_p90": numeric_or_none(scored["revenue_p50"].quantile(0.9)) if len(scored) else None,
        "high_risk_share": float(scored["risk_level"].eq("high").mean()) if len(scored) else None,
        "risk_counts": risk_counts,
        "payback_months_p50": numeric_or_none(scored["payback_months_p50"].median()) if len(scored) else None,
    }


def run(historical_path: Path, current_path: Path, scores_path: Path, output_dir: Path) -> dict[str, object]:
    historical = normalize_snapshot(read_table(historical_path))
    current = normalize_snapshot(read_table(current_path))
    classified = classify_points(historical, current)
    scores = pd.read_parquet(scores_path)[["h3", "revenue_p50", "risk_level", "payback_months_p50"]]
    enriched = attach_scores(classified, scores)
    output_dir.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(output_dir / "points.csv", index=False)
    groups = {
        name: summarize(enriched.loc[enriched["class"].eq(name)])
        for name in ("closed", "working", "uncertain")
    }
    summary = {
        "historical": str(historical_path),
        "current": str(current_path),
        "match_radius_m": MATCH_RADIUS_M,
        "groups": groups,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
