from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache, cached_property
from math import ceil
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import yaml

DEFAULT_RUNS = 200
DEFAULT_SEED = 2026
EARTH_RADIUS_M = 6_371_008.8
DISTANCE_SCALE_M = 100.0
MIN_DISTANCE_M = 100.0
SEATS_SCALE = 20.0
GRID_RADIUS_MARGIN = 2
GRID_EDGE_SAFETY_FACTOR = 0.5
QUANTILES = (0.1, 0.5, 0.9)
DISTANCE_TOLERANCE_M = 1e-6


class Niche(StrEnum):
    COFFEE = "coffee"
    PICKUP_POINT = "pickup_point"


class Source(StrEnum):
    OSM = "osm"
    MOS_RU = "mos_ru"


REQUIRED_PARAMETERS = {
    Niche.COFFEE: ("visits_per_resident_month", "visits_per_worker_month", "avg_check_rub"),
    Niche.PICKUP_POINT: ("orders_per_resident_month", "marketplace_share", "payout_per_order_rub"),
}
COMMON_PARAMETERS = ("max_walk_distance_m", "distance_decay_beta", "outside_option_weight")
OPTIONAL_PARAMETERS = {
    Niche.COFFEE: ("metro_visits_per_month", "metro_influence_distance_m", "transit_visits_per_stop_month"),
    Niche.PICKUP_POINT: ("max_pickup_distance_m",),
}


def preparation_distance(samples: pd.DataFrame) -> float:
    columns = [name for name in ("max_walk_distance_m", "max_pickup_distance_m") if name in samples]
    return float(samples[columns].max().max())


def parse_niche(niche: str) -> Niche:
    try:
        return Niche(niche)
    except ValueError as error:
        raise ValueError("Неизвестная ниша, выберите coffee или pickup_point") from error


@cache
def niche_defaults(niche: str) -> dict:
    selected = parse_niche(niche)
    with Path(__file__).with_name("niche_defaults.yaml").open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)[selected]


def demand_ranges(niche: str, ranges: Mapping[str, Mapping[str, object]]) -> dict:
    return {**niche_defaults(niche), **ranges}


def validate_parameters(niche: str, parameters: Mapping[str, float]) -> None:
    selected = parse_niche(niche)
    for name in (*REQUIRED_PARAMETERS[selected], *COMMON_PARAMETERS):
        value = parameters[name]
        if not np.isfinite(value) or value < 0:
            raise ValueError(f"Параметр {name} должен быть конечным и неотрицательным")
    for name in ("max_walk_distance_m", "distance_decay_beta"):
        if parameters[name] <= 0:
            raise ValueError(f"Параметр {name} должен быть положительным")
    for name in OPTIONAL_PARAMETERS[selected]:
        value = parameters.get(name, 0)
        if not np.isfinite(value) or value < 0:
            raise ValueError(f"Параметр {name} должен быть конечным и неотрицательным")
    if (
        parameters.get("metro_visits_per_month", 0) > 0
        and parameters.get("metro_influence_distance_m", 0) <= 0
    ):
        raise ValueError("Для спроса у метро нужен положительный радиус его влияния")
    if selected == Niche.COFFEE and parameters["outside_option_weight"] <= 0:
        raise ValueError("Параметр outside_option_weight для кофейни должен быть положительным")
    if selected == Niche.PICKUP_POINT and parameters["marketplace_share"] > 1:
        raise ValueError("Доля маркетплейса должна быть от 0 до 1")


def cell_demand(features: pd.DataFrame, niche: str, parameters: Mapping[str, float]) -> np.ndarray:
    selected = parse_niche(niche)
    residents = features["residents"].to_numpy(dtype=float)
    if selected == Niche.COFFEE:
        workers = features["workers"].to_numpy(dtype=float)
        return (
            residents * parameters["visits_per_resident_month"]
            + workers * parameters["visits_per_worker_month"]
            + passing_visits(features, parameters)
        ) * parameters["avg_check_rub"]
    return (
        residents
        * parameters["orders_per_resident_month"]
        * parameters["marketplace_share"]
        * parameters["payout_per_order_rub"]
    )


def passing_visits(features: pd.DataFrame, parameters: Mapping[str, float]) -> np.ndarray:
    visits = np.zeros(len(features))
    if parameters.get("metro_visits_per_month", 0) > 0:
        distances = pd.to_numeric(features.get("metro_dist_m", pd.Series(np.nan, index=features.index)))
        influence = (
            (1 - distances / parameters["metro_influence_distance_m"]).clip(lower=0, upper=1).fillna(0)
        )
        visits += influence.to_numpy() * parameters["metro_visits_per_month"]
    if parameters.get("transit_visits_per_stop_month", 0) > 0:
        stops = pd.to_numeric(features.get("transit_stops_n", pd.Series(0, index=features.index))).fillna(0)
        visits += stops.clip(lower=0).to_numpy() * parameters["transit_visits_per_stop_month"]
    return visits


def competitor_attractiveness(competitors: pd.DataFrame) -> np.ndarray:
    seats = pd.to_numeric(competitors["seats"], errors="coerce").fillna(0).to_numpy(dtype=float)
    return np.where(competitors["source"].eq(Source.MOS_RU), 1 + np.maximum(seats, 0) / SEATS_SCALE, 1)


def distances_m(origins: np.ndarray, destinations: np.ndarray) -> np.ndarray:
    origin_radians = np.radians(origins)
    destination_radians = np.radians(destinations)
    difference = destination_radians - origin_radians
    haversine = (
        np.sin(difference[:, 0] / 2) ** 2
        + np.cos(origin_radians[:, 0]) * np.cos(destination_radians[:, 0]) * np.sin(difference[:, 1] / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(haversine, 0, 1)))


@dataclass(frozen=True)
class DemandModel:
    features: pd.DataFrame
    niche: Niche
    origin_indices: np.ndarray
    destination_indices: np.ndarray
    distances: np.ndarray
    attraction: np.ndarray
    max_distance_m: float

    @cached_property
    def nearest_distances(self) -> np.ndarray:
        nearest = np.full(len(self.features), np.inf)
        selected = self.attraction[self.destination_indices] > 0
        np.minimum.at(nearest, self.origin_indices[selected], self.distances[selected])
        return nearest

    def competition_weights(self, parameters: Mapping[str, float]) -> np.ndarray:
        weights = (np.maximum(self.distances, MIN_DISTANCE_M) / DISTANCE_SCALE_M) ** (
            -parameters["distance_decay_beta"]
        )
        weights *= self.distances <= parameters["max_walk_distance_m"]
        if self.niche == Niche.PICKUP_POINT and parameters.get("max_pickup_distance_m", 0) > 0:
            nearest = self.nearest_distances[self.origin_indices]
            fallback = (
                (nearest > parameters["max_walk_distance_m"])
                & (self.distances <= parameters["max_pickup_distance_m"])
                & (np.abs(self.distances - nearest) <= DISTANCE_TOLERANCE_M)
            )
            weights[fallback] = 1
        return weights

    def candidate_terms(
        self, parameters: Mapping[str, float]
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        weights = self.competition_weights(parameters)
        pressure = np.bincount(
            self.origin_indices,
            weights=weights * self.attraction[self.destination_indices],
            minlength=len(self.features),
        )
        candidate_edges = self.destination_indices < len(self.features)
        origins = self.origin_indices[candidate_edges]
        destinations = self.destination_indices[candidate_edges]
        distances = self.distances[candidate_edges]
        candidate_weights = weights[candidate_edges].copy()
        candidate_pressure = pressure[origins].copy()
        if self.niche == Niche.PICKUP_POINT and parameters.get("max_pickup_distance_m", 0) > 0:
            nearest = self.nearest_distances[origins]
            uncovered = nearest > parameters["max_walk_distance_m"]
            walk = distances <= parameters["max_walk_distance_m"]
            fallback = uncovered & ~walk & (distances <= parameters["max_pickup_distance_m"])
            fallback &= distances <= nearest + DISTANCE_TOLERANCE_M
            candidate_weights[fallback] = 1
            closer = distances < nearest - DISTANCE_TOLERANCE_M
            candidate_pressure[uncovered & (walk | (fallback & closer))] = 0
        return origins, destinations, candidate_weights, candidate_pressure

    def revenue(self, parameters: Mapping[str, float], candidate_attraction: float = 1.0) -> np.ndarray:
        validate_parameters(self.niche, parameters)
        if not np.isfinite(candidate_attraction) or candidate_attraction <= 0:
            raise ValueError("Привлекательность кандидата должна быть положительной и конечной")
        if (
            max(parameters["max_walk_distance_m"], parameters.get("max_pickup_distance_m", 0))
            > self.max_distance_m
        ):
            raise ValueError("Радиус превышает подготовленную область, пересоздайте модель")
        origins, destinations, candidate_weights, pressure = self.candidate_terms(parameters)
        candidate_weights *= candidate_attraction
        denominators = candidate_weights + pressure + parameters["outside_option_weight"]
        shares = np.divide(
            candidate_weights,
            denominators,
            out=np.zeros_like(candidate_weights),
            where=denominators > 0,
        )
        return np.bincount(
            destinations,
            weights=cell_demand(self.features, self.niche, parameters)[origins] * shares,
            minlength=len(self.features),
        )


def prepare_model(
    features: pd.DataFrame, competitors: pd.DataFrame, niche: str, max_distance_m: float
) -> DemandModel:
    selected = parse_niche(niche)
    if not np.isfinite(max_distance_m) or max_distance_m <= 0:
        raise ValueError("Радиус должен быть положительным и конечным")
    if features.empty or not features["h3"].is_unique:
        raise ValueError("Нужны непустые признаки с уникальными ячейками H3")
    population = features[["residents", "workers"]].to_numpy(dtype=float)
    if not np.isfinite(population).all() or (population < 0).any():
        raise ValueError("Жители и рабочие места должны быть конечными и неотрицательными")
    cells = features["h3"].tolist()
    resolution = h3.get_resolution(cells[0])
    selected_competitors = competitors.loc[competitors["niche"].eq(selected)].copy()
    all_cells = list(dict.fromkeys([*cells, *selected_competitors["h3"].tolist()]))
    if any(h3.get_resolution(cell) != resolution for cell in all_cells):
        raise ValueError("Ячейки должны иметь одинаковое разрешение H3")
    indices = {cell: index for index, cell in enumerate(all_cells)}
    coordinates = np.array([h3.cell_to_latlng(cell) for cell in all_cells])
    radius = (
        ceil(
            max_distance_m / (h3.average_hexagon_edge_length(resolution, unit="m") * GRID_EDGE_SAFETY_FACTOR)
        )
        + GRID_RADIUS_MARGIN
    )
    origin_indices = []
    destination_indices = []
    for origin_index, cell in enumerate(cells):
        neighbors = sorted(
            indices[neighbor] for neighbor in h3.grid_disk(cell, radius) if neighbor in indices
        )
        origin_indices.extend([origin_index] * len(neighbors))
        destination_indices.extend(neighbors)
    origins = np.asarray(origin_indices, dtype=np.int64)
    destinations = np.asarray(destination_indices, dtype=np.int64)
    distances = distances_m(coordinates[origins], coordinates[destinations])
    inside = distances <= max_distance_m
    attraction = np.zeros(len(all_cells))
    np.add.at(
        attraction,
        selected_competitors["h3"].map(indices).to_numpy(dtype=np.int64),
        competitor_attractiveness(selected_competitors),
    )
    return DemandModel(
        features.copy(deep=True),
        selected,
        origins[inside],
        destinations[inside],
        distances[inside],
        attraction,
        max_distance_m,
    )


def sample_parameters(
    niche: str, ranges: Mapping[str, Mapping[str, object]], runs: int = DEFAULT_RUNS, seed: int = DEFAULT_SEED
) -> pd.DataFrame:
    selected = parse_niche(niche)
    if isinstance(runs, bool) or not isinstance(runs, int) or runs <= 0:
        raise ValueError("Число прогонов должно быть положительным целым")
    supplied_ranges = demand_ranges(selected, ranges)
    generator = np.random.default_rng(seed)
    samples = {}
    lower_parameters = {}
    upper_parameters = {}
    names = (*REQUIRED_PARAMETERS[selected], *COMMON_PARAMETERS)
    names += tuple(name for name in OPTIONAL_PARAMETERS[selected] if name in supplied_ranges)
    for name in names:
        bounds = supplied_ranges[name]
        lower, upper = float(bounds["p10"]), float(bounds["p90"])
        if not np.isfinite([lower, upper]).all() or lower > upper:
            raise ValueError(f"Проверьте границы p10 и p90 параметра {name}")
        lower_parameters[name] = lower
        upper_parameters[name] = upper
        samples[name] = generator.uniform(lower, upper, runs)
    validate_parameters(selected, lower_parameters)
    validate_parameters(selected, upper_parameters)
    frame = pd.DataFrame(samples)
    validate_parameters(selected, frame.min().to_dict())
    validate_parameters(selected, frame.max().to_dict())
    return frame


def simulate_demand(
    features: pd.DataFrame,
    competitors: pd.DataFrame,
    niche: str,
    ranges: Mapping[str, Mapping[str, object]],
    runs: int = DEFAULT_RUNS,
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    samples = sample_parameters(niche, ranges, runs, seed)
    model = prepare_model(features, competitors, niche, preparation_distance(samples))
    revenues = np.array([model.revenue(parameters) for parameters in samples.to_dict("records")])
    quantiles = np.quantile(revenues, QUANTILES, axis=0)
    return pd.DataFrame(
        {
            "h3": features["h3"].to_numpy(),
            "revenue_p10": quantiles[0],
            "revenue_p50": quantiles[1],
            "revenue_p90": quantiles[2],
        }
    )
