from enum import StrEnum

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from geostart.pipeline.geometry import METRIC_CRS, points_frame


class BuildingUse(StrEnum):
    RESIDENTIAL = "residential"
    UNSPECIFIED = "unspecified"
    OFFICE = "office"
    RETAIL = "retail"
    EDUCATION = "education"
    HEALTH = "health"
    INDUSTRIAL = "industrial"
    PUBLIC = "public"
    OTHER = "other"


BUILDING_USE_BY_TAG = {
    **dict.fromkeys(
        [
            "apartments",
            "residential",
            "house",
            "detached",
            "semidetached_house",
            "terrace",
            "dormitory",
            "bungalow",
        ],
        BuildingUse.RESIDENTIAL,
    ),
    "yes": BuildingUse.UNSPECIFIED,
    **dict.fromkeys(["office", "commercial"], BuildingUse.OFFICE),
    **dict.fromkeys(["retail", "supermarket", "mall", "kiosk"], BuildingUse.RETAIL),
    **dict.fromkeys(["school", "university", "college", "kindergarten"], BuildingUse.EDUCATION),
    **dict.fromkeys(["hospital", "clinic"], BuildingUse.HEALTH),
    **dict.fromkeys(["industrial", "warehouse", "factory", "manufacture"], BuildingUse.INDUSTRIAL),
    **dict.fromkeys(["public", "government", "civic"], BuildingUse.PUBLIC),
}
DEFAULT_LEVELS = {
    BuildingUse.RESIDENTIAL: 5,
    BuildingUse.UNSPECIFIED: 2,
    BuildingUse.OFFICE: 4,
    BuildingUse.RETAIL: 2,
    BuildingUse.EDUCATION: 3,
    BuildingUse.HEALTH: 4,
    BuildingUse.INDUSTRIAL: 1,
    BuildingUse.PUBLIC: 3,
    BuildingUse.OTHER: 1,
}
FLOOR_AREA_PER_WORKER_M2 = {
    BuildingUse.OFFICE: 20.0,
    BuildingUse.RETAIL: 40.0,
    BuildingUse.EDUCATION: 30.0,
    BuildingUse.HEALTH: 30.0,
    BuildingUse.INDUSTRIAL: 100.0,
    BuildingUse.PUBLIC: 30.0,
}
MAX_PLAUSIBLE_LEVELS = 100
MIN_BUILDING_FOOTPRINT_M2 = 20.0
SMALL_UNSPECIFIED_FOOTPRINT_M2 = 100.0
MULTISTOREY_LEVELS = 4
UNSPECIFIED_BUSINESS_RESIDENTIAL_SHARE = 0.3
UNSPECIFIED_MULTISTOREY_RESIDENTIAL_SHARE = 0.8
UNSPECIFIED_LOWRISE_RESIDENTIAL_SHARE = 0.4
METRO_SEARCH_RADIUS_M = 5_000


def parse_levels(raw_levels: pd.Series) -> pd.Series:
    numbers = pd.to_numeric(raw_levels.astype("string").str.extract(r"(\d+(?:\.\d+)?)")[0], errors="coerce")
    return numbers.where((numbers > 0) & (numbers <= MAX_PLAUSIBLE_LEVELS))


def classify_buildings(buildings: pd.DataFrame) -> gpd.GeoDataFrame:
    frame = gpd.GeoDataFrame(buildings, geometry=shapely.from_wkb(buildings["wkb"]), crs="EPSG:4326")
    frame["use"] = frame["building"].map(BUILDING_USE_BY_TAG).fillna(BuildingUse.OTHER)
    metric = frame.to_crs(METRIC_CRS)
    frame["footprint_m2"] = metric.area.to_numpy()
    frame = frame[frame["footprint_m2"] >= MIN_BUILDING_FOOTPRINT_M2].copy()
    default_levels = frame["use"].map(DEFAULT_LEVELS).astype(float)
    frame["levels"] = parse_levels(frame["building:levels"]).fillna(default_levels)
    frame["floor_area_m2"] = frame["footprint_m2"] * frame["levels"]
    centroids = frame.to_crs(METRIC_CRS).centroid.to_crs("EPSG:4326")
    frame["lon"] = centroids.x.to_numpy()
    frame["lat"] = centroids.y.to_numpy()
    return frame.drop(columns=["wkb"])


def unspecified_residential_share(buildings: pd.DataFrame) -> np.ndarray:
    has_business_tags = buildings[["amenity", "shop", "office"]].notna().any(axis=1)
    return np.select(
        [
            buildings["footprint_m2"] < SMALL_UNSPECIFIED_FOOTPRINT_M2,
            has_business_tags,
            buildings["levels"] >= MULTISTOREY_LEVELS,
        ],
        [0.0, UNSPECIFIED_BUSINESS_RESIDENTIAL_SHARE, UNSPECIFIED_MULTISTOREY_RESIDENTIAL_SHARE],
        default=UNSPECIFIED_LOWRISE_RESIDENTIAL_SHARE,
    )


def residential_floor_area(buildings: pd.DataFrame) -> pd.Series:
    share = np.where(
        buildings["use"] == BuildingUse.RESIDENTIAL,
        1.0,
        np.where(buildings["use"] == BuildingUse.UNSPECIFIED, unspecified_residential_share(buildings), 0.0),
    )
    return buildings["floor_area_m2"] * share


def worker_capacity(buildings: pd.DataFrame) -> pd.Series:
    area_per_worker = buildings["use"].map(FLOOR_AREA_PER_WORKER_M2)
    return (buildings["floor_area_m2"] / area_per_worker).fillna(0.0)


def sum_by_cell(values: pd.Series, cells: pd.Series, all_cells: pd.Index) -> pd.Series:
    return values.groupby(cells).sum().reindex(all_cells, fill_value=0.0)


def count_by_cell(mask: pd.Series, cells: pd.Series, all_cells: pd.Index) -> pd.Series:
    return mask.astype(int).groupby(cells).sum().reindex(all_cells, fill_value=0).astype("int64")


def nearest_distance_m(hexes: gpd.GeoDataFrame, targets: pd.DataFrame) -> pd.Series:
    if targets.empty:
        return pd.Series(np.nan, index=hexes.index)
    centers = points_frame(hexes[["lon", "lat"]].copy()).to_crs(METRIC_CRS)
    points = points_frame(targets[["lon", "lat"]].copy()).to_crs(METRIC_CRS)
    joined = gpd.sjoin_nearest(
        centers, points, how="left", max_distance=METRO_SEARCH_RADIUS_M, distance_col="distance"
    )
    distances = joined.groupby(level=0)["distance"].min()
    return distances.reindex(hexes.index).round(0)
