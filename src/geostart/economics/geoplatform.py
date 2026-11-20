from collections.abc import Sequence
from dataclasses import dataclass
from math import cos, radians

import numpy as np
import pandas as pd

from geostart import settings
from geostart.economics.sampling import QUANTILE_LEVELS, stratified_levels
from geostart.model.demand import (
    DISTANCE_SCALE_M,
    MIN_DISTANCE_M,
    DemandKind,
    competitor_attractiveness,
    demand_kind,
    distances_m,
    limit_revenue,
)

SQUARE_SIZE_M = 500.0
METERS_PER_DEGREE_LAT = 111_320.0
STUB_PROVIDER = "заглушка геоплатформы банка"
STUB_LAYER_VERSION = "stub-2026-11-20"
LEVEL_SEED_STREAM = 4
PLATFORM_ORDERS_ERROR = (
    "Геоплатформа передаёт траты покупателей, для пункта выдачи используйте источник geostart"
)
LOWER_LEVEL, MIDDLE_LEVEL, UPPER_LEVEL = QUANTILE_LEVELS


@dataclass(frozen=True)
class SquareLayer:
    square_id: str
    south: float
    west: float
    north: float
    east: float
    spend_p10: float
    spend_p50: float
    spend_p90: float
    footfall_p50: float | None = None


@dataclass(frozen=True)
class SquareGrid:
    origin_lat: float
    origin_lon: float
    step_lat: float
    step_lon: float

    @classmethod
    def around(cls, latitudes: np.ndarray, longitudes: np.ndarray) -> "SquareGrid":
        center = float(np.mean(latitudes))
        step_lat = SQUARE_SIZE_M / METERS_PER_DEGREE_LAT
        step_lon = SQUARE_SIZE_M / (METERS_PER_DEGREE_LAT * cos(radians(center)))
        origin_lat = float(np.floor(latitudes.min() / step_lat) * step_lat)
        origin_lon = float(np.floor(longitudes.min() / step_lon) * step_lon)
        return cls(origin_lat, origin_lon, step_lat, step_lon)

    def indices(self, latitudes: np.ndarray, longitudes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rows = np.floor((latitudes - self.origin_lat) / self.step_lat).astype(int)
        columns = np.floor((longitudes - self.origin_lon) / self.step_lon).astype(int)
        return rows, columns

    def bounds(self, row: int, column: int) -> tuple[float, float, float, float]:
        south = self.origin_lat + row * self.step_lat
        west = self.origin_lon + column * self.step_lon
        return south, west, south + self.step_lat, west + self.step_lon


def stub_path(city: str):
    return settings.data_dir() / "geoplatform" / f"{city}.parquet"


def load_stub(city: str, niche: str) -> list[SquareLayer]:
    path = stub_path(city)
    if not path.is_file():
        raise FileNotFoundError(
            f"Нет слоёв заглушки геоплатформы для города {city}, выполните "
            f"uv run python -m geostart.economics.geoplatform_stub --city {city}"
        )
    frame = pd.read_parquet(path)
    columns = [f"spend_{niche}_p10", f"spend_{niche}_p50", f"spend_{niche}_p90"]
    if columns[1] not in frame:
        raise ValueError(f"В слоях заглушки геоплатформы нет трат по нише {niche}, пересоберите слои")
    return [
        SquareLayer(
            row.square_id,
            row.south,
            row.west,
            row.north,
            row.east,
            float(getattr(row, columns[0])),
            float(getattr(row, columns[1])),
            float(getattr(row, columns[2])),
            float(row.footfall_day_p50),
        )
        for row in frame.itertuples(index=False)
    ]


def spend_at_levels(layer: SquareLayer, levels: np.ndarray) -> np.ndarray:
    lower = (layer.spend_p50 - layer.spend_p10) / (MIDDLE_LEVEL - LOWER_LEVEL)
    upper = (layer.spend_p90 - layer.spend_p50) / (UPPER_LEVEL - MIDDLE_LEVEL)
    values = np.where(
        levels < MIDDLE_LEVEL,
        layer.spend_p50 - (MIDDLE_LEVEL - levels) * lower,
        layer.spend_p50 + (levels - MIDDLE_LEVEL) * upper,
    )
    return np.maximum(values, 0.0)


def square_of(layers: Sequence[SquareLayer], latitudes: np.ndarray, longitudes: np.ndarray) -> np.ndarray:
    result = np.full(len(latitudes), -1)
    for index, layer in enumerate(layers):
        inside = (
            (latitudes >= layer.south)
            & (latitudes < layer.north)
            & (longitudes >= layer.west)
            & (longitudes < layer.east)
        )
        result[inside & (result < 0)] = index
    return result


@dataclass(frozen=True)
class PlatformDemand:
    revenue: np.ndarray
    squares_used: int
    spend_in_reach_p50: float
    footfall_p50: float | None


def platform_revenue(
    features: pd.DataFrame,
    competitors: pd.DataFrame,
    niche: str,
    samples: pd.DataFrame,
    layers: Sequence[SquareLayer],
    lat: float,
    lon: float,
    seed: int,
) -> PlatformDemand:
    if demand_kind(niche) != DemandKind.VISITS:
        raise ValueError(PLATFORM_ORDERS_ERROR)
    if not layers:
        raise ValueError("Нужен хотя бы один квадрат геоплатформы с тратами")
    reach = float(samples["max_walk_distance_m"].max())
    city_lat = features["lat"].to_numpy(dtype=float)
    city_lon = features["lon"].to_numpy(dtype=float)
    owners = square_of(layers, city_lat, city_lon)
    cells_per_square = np.bincount(owners[owners >= 0], minlength=len(layers))
    point = np.tile([lat, lon], (len(features), 1))
    to_point = distances_m(point, np.column_stack([city_lat, city_lon]))
    near = (to_point <= reach) & (owners >= 0)
    if not near.any():
        raise ValueError("В радиусе доступности точки нет ячеек с тратами геоплатформы")
    cell_lat, cell_lon = city_lat[near], city_lon[near]
    cell_square = owners[near]
    cell_distance = to_point[near]
    selected = competitors.loc[competitors["niche"].eq(niche)]
    comp_lat = selected["lat"].to_numpy(dtype=float)
    comp_lon = selected["lon"].to_numpy(dtype=float)
    comp_point = distances_m(np.tile([lat, lon], (len(selected), 1)), np.column_stack([comp_lat, comp_lon]))
    close = comp_point <= 2 * reach
    comp_lat, comp_lon = comp_lat[close], comp_lon[close]
    attraction = competitor_attractiveness(selected.loc[close])
    if len(comp_lat):
        pairs_origin = np.repeat(np.column_stack([cell_lat, cell_lon]), len(comp_lat), axis=0)
        pairs_target = np.tile(np.column_stack([comp_lat, comp_lon]), (len(cell_lat), 1))
        comp_distance = distances_m(pairs_origin, pairs_target).reshape(len(cell_lat), len(comp_lat))
    else:
        comp_distance = np.zeros((len(cell_lat), 0))
    levels = stratified_levels(
        len(samples), np.random.default_rng(np.random.SeedSequence([seed, LEVEL_SEED_STREAM]))
    )
    used = np.unique(cell_square)
    square_spend = {index: spend_at_levels(layers[index], levels) for index in used}
    revenue = np.zeros(len(samples))
    for run, parameters in enumerate(samples.to_dict("records")):
        beta = parameters["distance_decay_beta"]
        walk = parameters["max_walk_distance_m"]
        own = (np.maximum(cell_distance, MIN_DISTANCE_M) / DISTANCE_SCALE_M) ** -beta * (
            cell_distance <= walk
        )
        weights = (np.maximum(comp_distance, MIN_DISTANCE_M) / DISTANCE_SCALE_M) ** -beta * (
            comp_distance <= walk
        )
        pressure = weights @ attraction if len(comp_lat) else np.zeros(len(cell_lat))
        share = np.divide(
            own, own + pressure + parameters["outside_option_weight"], out=np.zeros_like(own), where=own > 0
        )
        spend = np.array([square_spend[index][run] for index in cell_square]) / cells_per_square[cell_square]
        revenue[run] = limit_revenue(np.array([float((spend * share).sum())]), niche, parameters)[0]
    middle = np.full(len(used), MIDDLE_LEVEL)
    reach_spend = sum(float(spend_at_levels(layers[index], middle[:1])[0]) for index in used)
    footfalls = [layers[index].footfall_p50 for index in used if layers[index].footfall_p50 is not None]
    return PlatformDemand(revenue, len(used), reach_spend, float(np.sum(footfalls)) if footfalls else None)
