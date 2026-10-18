import numpy as np
import pandas as pd

from geostart.model.demand import (
    DISTANCE_SCALE_M,
    DISTANCE_TOLERANCE_M,
    MIN_DISTANCE_M,
    DemandModel,
    Niche,
    cell_demand,
    limit_revenue,
)


def simulate_revenues(
    model: DemandModel, samples: pd.DataFrame, candidate_index: int | None = None
) -> np.ndarray:
    max_walk = float(samples.max_walk_distance_m.max())
    if max_walk > model.max_distance_m:
        raise ValueError("Радиус превышает подготовленную область, пересоздайте модель")
    active = model.distances <= max_walk
    fallback_enabled = model.niche == Niche.PICKUP_POINT and "max_pickup_distance_m" in samples
    nearest = model.nearest_distances if fallback_enabled else None
    if fallback_enabled:
        max_pickup = float(samples.max_pickup_distance_m.max())
        if max_pickup > model.max_distance_m:
            raise ValueError("Радиус превышает подготовленную область, пересоздайте модель")
        local_nearest = nearest[model.origin_indices]
        active |= (
            (local_nearest > float(samples.max_walk_distance_m.min()))
            & (model.distances <= max_pickup)
            & (model.distances <= local_nearest + DISTANCE_TOLERANCE_M)
        )
    origins = model.origin_indices[active]
    destinations = model.destination_indices[active]
    distances = model.distances[active]
    normalized = np.maximum(distances, MIN_DISTANCE_M) / DISTANCE_SCALE_M
    attractions = model.attraction[destinations]
    candidate_edges = (
        destinations < len(model.features) if candidate_index is None else destinations == candidate_index
    )
    candidate_origins = origins[candidate_edges]
    candidate_destinations = destinations[candidate_edges]
    candidate_distances = distances[candidate_edges]
    size = len(model.features) if candidate_index is None else 1
    results = np.zeros((len(samples), size))
    for run, parameters in enumerate(samples.to_dict("records")):
        weights = normalized ** -parameters["distance_decay_beta"]
        weights *= distances <= parameters["max_walk_distance_m"]
        if fallback_enabled:
            far = nearest[origins] > parameters["max_walk_distance_m"]
            selected = (
                far
                & (distances <= parameters["max_pickup_distance_m"])
                & (np.abs(distances - nearest[origins]) <= DISTANCE_TOLERANCE_M)
            )
            weights[selected] = 1
        pressure = np.bincount(origins, weights=weights * attractions, minlength=len(model.features))
        candidate_weights = weights[candidate_edges].copy()
        candidate_pressure = pressure[candidate_origins]
        if fallback_enabled:
            local_nearest = nearest[candidate_origins]
            uncovered = local_nearest > parameters["max_walk_distance_m"]
            walk = candidate_distances <= parameters["max_walk_distance_m"]
            fallback = (
                uncovered
                & ~walk
                & (candidate_distances <= parameters["max_pickup_distance_m"])
                & (candidate_distances <= local_nearest + DISTANCE_TOLERANCE_M)
            )
            candidate_weights[fallback] = 1
            closer = candidate_distances < local_nearest - DISTANCE_TOLERANCE_M
            candidate_pressure[uncovered & (walk | (fallback & closer))] = 0
        denominators = candidate_weights + candidate_pressure + parameters["outside_option_weight"]
        shares = np.divide(
            candidate_weights, denominators, out=np.zeros_like(candidate_weights), where=denominators > 0
        )
        captured = cell_demand(model.features, model.niche, parameters)[candidate_origins] * shares
        if candidate_index is None:
            results[run] = np.bincount(candidate_destinations, weights=captured, minlength=size)
        else:
            results[run, 0] = np.bincount(np.zeros(len(captured), dtype=int), weights=captured, minlength=1)[
                0
            ]
        results[run] = limit_revenue(results[run], model.niche, parameters)
    return results
