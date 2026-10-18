from dataclasses import replace

import h3
import numpy as np
import pandas as pd

from geostart.model.demand import DemandModel, competitor_attractiveness, distances_m
from geostart.schemas import Factor

COMPETITOR_RADIUS_M = 500.0
MIN_DISTRICT_CELLS = 30
FACTOR_NAMES = {
    "residents": ("Жители ячейки", "чел."),
    "workers": ("Рабочие места ячейки", "мест"),
    "competitors_500m": ("Конкуренты в радиусе 500 м", "шт."),
    "metro_dist_m": ("Расстояние до метро", "м"),
    "transit_stops_n": ("Остановки ячейки", "шт."),
    "offices_n": ("Офисы ячейки", "шт."),
    "education_n": ("Учебные заведения ячейки", "шт."),
    "malls_n": ("Торговые центры ячейки", "шт."),
}


def competition_reference(city_features: pd.DataFrame, counts: np.ndarray, district: str) -> float:
    district_mask = city_features["district"].eq(district).to_numpy()
    reference = counts[district_mask] if district_mask.sum() >= MIN_DISTRICT_CELLS else counts
    return float(np.median(reference))


def bounded_competition_effect(baseline: float, counterfactual: float) -> float:
    return float(np.clip(baseline - counterfactual, -baseline, baseline))


def competition_counterfactual(
    model: DemandModel,
    candidate_index: int,
    competitors: pd.DataFrame,
    desired_count: float,
) -> DemandModel:
    candidate_cell = model.features.iloc[candidate_index]["h3"]
    center = np.asarray(h3.cell_to_latlng(candidate_cell))
    selected = competitors.loc[competitors["niche"].eq(model.niche)]
    coordinates = selected[["lat", "lon"]].to_numpy(dtype=float)
    distances = distances_m(np.tile(center, (len(selected), 1)), coordinates)
    nearby = selected.loc[distances <= COMPETITOR_RADIUS_M]
    cells = list(dict.fromkeys([*model.features["h3"], *selected["h3"]]))
    indices = {cell: index for index, cell in enumerate(cells)}
    attraction = model.attraction.copy()
    if nearby.empty:
        attraction[candidate_index] += desired_count
    else:
        adjustment = desired_count / len(nearby) - 1
        np.add.at(
            attraction,
            nearby["h3"].map(indices).to_numpy(dtype=int),
            competitor_attractiveness(nearby) * adjustment,
        )
    return replace(model, attraction=np.maximum(attraction, 0))


def explain_factors(
    model: DemandModel,
    candidate_index: int,
    city_features: pd.DataFrame,
    competitors: pd.DataFrame,
    competitor_counts: np.ndarray,
    nearby_count: int,
    samples: pd.DataFrame,
    baseline_p50: float,
) -> list[Factor]:
    candidate = model.features.iloc[candidate_index]
    parameters = samples.to_dict("records")
    factors = []
    for code, (name, unit) in FACTOR_NAMES.items():
        value = nearby_count if code == "competitors_500m" else candidate[code]
        if pd.isna(value):
            continue
        counterfactual = model
        if code in ("residents", "workers", "metro_dist_m", "transit_stops_n"):
            changed = model.features.copy(deep=True)
            changed[code] = changed[code].astype(float)
            changed.loc[changed.index[candidate_index], code] = float(city_features[code].median())
            counterfactual = replace(model, features=changed)
        elif code == "competitors_500m":
            counterfactual = competition_counterfactual(
                model,
                candidate_index,
                competitors,
                competition_reference(city_features, competitor_counts, str(candidate["district"])),
            )
        else:
            factors.append(Factor(code=code, name=name, value=float(value), unit=unit, effect_rub=0))
            continue
        revenues = [counterfactual.revenue(item)[candidate_index] for item in parameters]
        effect = baseline_p50 - float(np.median(revenues))
        if code == "competitors_500m":
            effect = bounded_competition_effect(baseline_p50, float(np.median(revenues)))
        factors.append(Factor(code=code, name=name, value=float(value), unit=unit, effect_rub=effect))
    return sorted(factors, key=lambda factor: abs(factor.effect_rub), reverse=True)
