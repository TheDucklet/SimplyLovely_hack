from collections.abc import Mapping
from dataclasses import dataclass
from math import ceil

import numpy as np
import pandas as pd

from geostart.model.demand import (
    DemandModel,
    cell_demand,
    competitor_attractiveness,
    demand_ranges,
)

TOP_FRACTION = 0.2


def roc_auc(positive: np.ndarray, negative: np.ndarray) -> float:
    if len(positive) == 0 or len(negative) == 0:
        raise ValueError("Для ROC AUC нужны точки и контрольные ячейки")
    combined = np.concatenate([positive, negative])
    if not np.isfinite(combined).all():
        raise ValueError("Оценки ROC AUC должны быть конечными")
    ranks = pd.Series(combined).rank(method="average").to_numpy()
    rank_sum = ranks[: len(positive)].sum()
    return float((rank_sum - len(positive) * (len(positive) + 1) / 2) / (len(positive) * len(negative)))


def edge_weights(model: DemandModel, parameters: Mapping[str, float]) -> np.ndarray:
    return model.competition_weights(parameters)


@dataclass(frozen=True)
class PointSimulation:
    revenues: np.ndarray
    reachable_demand: np.ndarray


def point_simulation(
    model: DemandModel,
    competitors: pd.DataFrame,
    samples: pd.DataFrame,
    candidate_attractions: np.ndarray | None = None,
) -> PointSimulation:
    selected = competitors.loc[competitors["niche"].eq(model.niche)]
    indices = pd.Series(np.arange(len(model.features)), index=model.features["h3"])
    point_indices = selected["h3"].map(indices)
    if point_indices.isna().any():
        raise ValueError("Для каждой точки нужна ячейка кандидата, добавьте недостающие ячейки")
    point_indices = point_indices.to_numpy(dtype=int)
    attractions = competitor_attractiveness(selected)
    candidates = (
        np.ones(len(selected)) if candidate_attractions is None else np.asarray(candidate_attractions)
    )
    if candidates.shape != attractions.shape or not np.isfinite(candidates).all() or (candidates <= 0).any():
        raise ValueError("Для каждой точки нужна положительная конечная привлекательность")
    candidate_edges = np.flatnonzero(model.destination_indices < len(model.features))
    edge_order = candidate_edges[np.argsort(model.destination_indices[candidate_edges], kind="stable")]
    edge_counts = np.bincount(model.destination_indices[candidate_edges], minlength=len(model.features))
    offsets = np.concatenate([[0], np.cumsum(edge_counts)])
    point_edges = [edge_order[offsets[index] : offsets[index + 1]] for index in point_indices]
    point_edges = np.concatenate(point_edges) if point_edges else np.array([], dtype=int)
    slots = np.repeat(np.arange(len(selected)), edge_counts[point_indices])
    origins = model.origin_indices[point_edges]
    results = np.zeros((len(samples), len(selected)))
    reachable = np.zeros_like(results)
    for run_index, parameters in enumerate(samples.to_dict("records")):
        weights = edge_weights(model, parameters)
        pressure = np.bincount(
            model.origin_indices,
            weights=weights * model.attraction[model.destination_indices],
            minlength=len(model.features),
        )
        point_weights = weights[point_edges]
        demand = cell_demand(model.features, model.niche, parameters)
        remaining = np.maximum(pressure[origins] - attractions[slots] * point_weights, 0)
        candidate_weights = candidates[slots] * point_weights
        denominators = remaining + candidate_weights + parameters["outside_option_weight"]
        shares = np.divide(
            candidate_weights, denominators, out=np.zeros_like(candidate_weights), where=denominators > 0
        )
        results[run_index] = np.bincount(slots, weights=demand[origins] * shares, minlength=len(selected))
        reachable[run_index] = np.bincount(
            slots, weights=demand[origins] * (point_weights > 0), minlength=len(selected)
        )
    return PointSimulation(results, reachable)


def leave_one_out_potentials(
    model: DemandModel,
    competitors: pd.DataFrame,
    samples: pd.DataFrame,
) -> np.ndarray:
    return np.median(point_simulation(model, competitors, samples).revenues, axis=0)


def validation_metrics(
    features: pd.DataFrame,
    competitors: pd.DataFrame,
    niche: str,
    revenues: np.ndarray,
    point_potentials: np.ndarray,
    seed: int,
) -> tuple[dict, pd.DataFrame]:
    points = competitors.loc[competitors["niche"].eq(niche)].copy().reset_index(drop=True)
    index = pd.Series(np.arange(len(features)), index=features["h3"])
    point_indices = points["h3"].map(index).to_numpy(dtype=int)
    occupied = np.unique(point_indices)
    available = np.setdiff1d(np.arange(len(features)), occupied)
    generator = np.random.default_rng(seed)
    controls = generator.choice(available, size=min(len(points), len(available)), replace=False)
    city_potentials = revenues.copy()
    for cell_index in occupied:
        city_potentials[cell_index] = np.median(point_potentials[point_indices == cell_index])
    top_count = ceil(TOP_FRACTION * len(features))
    ranked = np.lexsort((features["h3"].to_numpy(), -city_potentials))
    top_mask = np.zeros(len(features), dtype=bool)
    top_mask[ranked[:top_count]] = True
    top_share = float(top_mask[point_indices].mean())
    baseline_share = top_count / len(features)
    metrics = {
        "points": len(points),
        "occupied_cells": len(occupied),
        "controls": len(controls),
        "seed": seed,
        "roc_auc": roc_auc(point_potentials, revenues[controls]),
        "naive_auc": roc_auc(revenues[point_indices], revenues[controls]),
        "top20_share": top_share,
        "random_top_share": baseline_share,
        "lift": top_share / baseline_share,
        "existing_revenue_p50": float(np.median(point_potentials)),
        "random_revenue_p50": float(np.median(revenues[controls])),
        "existing_distribution": np.quantile(point_potentials, [0.1, 0.5, 0.9]).tolist(),
        "random_distribution": np.quantile(revenues[controls], [0.1, 0.5, 0.9]).tolist(),
    }
    observations = points[["poi_id", "h3"]].copy()
    observations["potential_loo_p50"] = point_potentials
    observations["potential_new_p50"] = revenues[point_indices]
    observations["top20"] = top_mask[point_indices]
    return metrics, observations


def sensitivity(
    model: DemandModel,
    samples: pd.DataFrame,
    ranges: Mapping[str, Mapping[str, object]],
) -> pd.DataFrame:
    baseline = np.median([model.revenue(item) for item in samples.to_dict("records")], axis=0)
    effective = demand_ranges(model.niche, ranges)
    rows = []
    for name in samples.columns:
        endpoint_potentials = []
        for endpoint in ("p10", "p90"):
            changed = samples.copy()
            changed[name] = float(effective[name][endpoint])
            potentials = np.median([model.revenue(item) for item in changed.to_dict("records")], axis=0)
            endpoint_potentials.append(potentials)
        lower, upper = endpoint_potentials
        rows.append(
            {
                "parameter": name,
                "input_p10": float(effective[name]["p10"]),
                "input_p90": float(effective[name]["p90"]),
                "revenue_at_p10": float(np.median(lower)),
                "revenue_at_p90": float(np.median(upper)),
                "median_cell_effect_rub": float(np.median(upper - lower)),
                "mean_absolute_effect_rub": float(np.mean(np.abs(upper - lower))),
                "city_median_change_pct": float(
                    (np.median(upper) - np.median(lower)) / np.median(baseline) * 100
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("mean_absolute_effect_rub", ascending=False).reset_index(drop=True)


def pickup_decomposition(model: DemandModel, parameters: Mapping[str, float], candidate_index: int) -> dict:
    all_origins, destinations, weights, pressure = model.candidate_terms(parameters)
    candidate_edges = (destinations == candidate_index) & (weights > 0)
    origins = all_origins[candidate_edges]
    candidate_weights = weights[candidate_edges]
    residents = model.features["residents"].to_numpy(dtype=float)[origins]
    population = float(residents.sum())
    orders = residents * parameters["orders_per_resident_month"] * parameters["marketplace_share"]
    total_orders = float(orders.sum())
    denominators = candidate_weights + pressure[candidate_edges] + parameters["outside_option_weight"]
    captured_orders = float(np.sum(orders * candidate_weights / denominators))
    outside_orders = float(np.sum(orders * parameters["outside_option_weight"] / denominators))
    outside_share = outside_orders / total_orders if total_orders else 0
    conditional_share = (
        captured_orders / (total_orders - outside_orders) if total_orders > outside_orders else 0
    )
    return {
        "h3": model.features.iloc[candidate_index]["h3"],
        "residents_catchment": population,
        "orders_per_resident_month": parameters["orders_per_resident_month"],
        "marketplace_share": parameters["marketplace_share"],
        "payout_per_order_rub": parameters["payout_per_order_rub"],
        "outside_option_weight": parameters["outside_option_weight"],
        "outside_share": outside_share,
        "conditional_huff_share": conditional_share,
        "captured_orders": captured_orders,
        "revenue": captured_orders * parameters["payout_per_order_rub"],
    }
