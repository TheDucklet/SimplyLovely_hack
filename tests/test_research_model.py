from pathlib import Path

import h3
import numpy as np
import pandas as pd
import pytest

from geostart.model.demand import cell_demand, distances_m, prepare_model
from geostart.model.factors import explain_factors
from geostart.model.validation import leave_one_out_potentials, point_simulation
from geostart.pipeline.fixtures import write_fixtures

PARAMETERS = {
    "orders_per_resident_month": 4,
    "marketplace_share": 0.8,
    "payout_per_order_rub": 70,
    "max_walk_distance_m": 100,
    "max_pickup_distance_m": 1500,
    "distance_decay_beta": 2.5,
    "outside_option_weight": 0.05,
}


@pytest.fixture
def pickup_data(tmp_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    write_fixtures("moscow", tmp_path)
    features = pd.read_parquet(tmp_path / "hex_features.parquet")
    center = h3.latlng_to_cell(55.7558, 37.6176, 9)
    coordinates = np.array([h3.cell_to_latlng(cell) for cell in features.h3])
    center_coordinates = np.tile(h3.cell_to_latlng(center), (len(features), 1))
    distances = distances_m(center_coordinates, coordinates)
    cells = [center]
    cells += [
        features.loc[(distances > lower) & (distances < upper)].iloc[0].h3
        for lower, upper in ((200, 400), (500, 700), (900, 1100))
    ]
    features = features.set_index("h3").loc[cells].reset_index()
    features["residents"] = [100, 0, 0, 0]
    features["workers"] = 0
    points = pd.DataFrame(
        {"poi_id": ["near", "far"], "h3": cells[2:], "niche": "pickup_point", "source": "osm", "seats": None}
    )
    coordinates = np.array([h3.cell_to_latlng(cell) for cell in points.h3])
    points["lat"] = coordinates[:, 0]
    points["lon"] = coordinates[:, 1]
    return features, points


def test_pickup_fallback_uses_nearest_points_and_preserves_demand(pickup_data) -> None:
    features, points = pickup_data
    model = prepare_model(features, points, "pickup_point", 1500)
    samples = pd.DataFrame([PARAMETERS])
    actual = point_simulation(model, points, samples, np.ones(len(points))).revenues[0]
    demand = cell_demand(features, "pickup_point", PARAMETERS).sum()
    assert actual[0] == pytest.approx(demand / 1.05)
    assert actual[1] == 0
    assert actual.sum() <= demand
    without = {**PARAMETERS, "max_pickup_distance_m": 0}
    assert point_simulation(model, points, pd.DataFrame([without])).revenues.sum() == 0
    candidate = model.revenue(PARAMETERS)
    assert candidate[1] == pytest.approx(demand / 1.05)
    assert candidate[2] == pytest.approx(demand / 2.05)
    assert candidate[3] == 0


def test_pickup_fallback_does_not_bypass_walk_or_radius(pickup_data) -> None:
    features, points = pickup_data
    model = prepare_model(features, points, "pickup_point", 1500)
    assert model.revenue({**PARAMETERS, "max_pickup_distance_m": 400})[2] == 0
    walk = {**PARAMETERS, "max_walk_distance_m": 800}
    assert model.revenue(walk)[3] == 0
    assert model.revenue(walk)[2] > 0


def test_pickup_fallback_leave_one_out_matches_direct_removal(pickup_data) -> None:
    features, points = pickup_data
    model = prepare_model(features, points, "pickup_point", 1500)
    samples = pd.DataFrame([PARAMETERS])
    potentials = leave_one_out_potentials(model, points, samples)
    for index, point in points.iterrows():
        changed = prepare_model(features, points.drop(index=index), "pickup_point", 1500)
        candidate = int(np.flatnonzero(features.h3.eq(point.h3))[0])
        assert potentials[index] == pytest.approx(changed.revenue(PARAMETERS)[candidate])


def test_coffee_passing_demand_handles_distance_and_missing_features() -> None:
    features = pd.DataFrame(
        {
            "residents": [0] * 4,
            "workers": [0] * 4,
            "metro_dist_m": [0, 100, 400, np.nan],
            "transit_stops_n": [1, 2, 0, np.nan],
        }
    )
    parameters = {
        "visits_per_resident_month": 2,
        "visits_per_worker_month": 6,
        "avg_check_rub": 300,
        "metro_visits_per_month": 1000,
        "metro_influence_distance_m": 200,
        "transit_visits_per_stop_month": 90,
    }
    np.testing.assert_allclose(cell_demand(features, "coffee", parameters), np.array([1090, 680, 0, 0]) * 300)
    np.testing.assert_array_equal(cell_demand(features[["residents", "workers"]], "coffee", parameters), 0)


@pytest.mark.parametrize("metro_distance,positive", [(0, True), (1500, False)])
def test_metro_factor_is_readable_in_top_five(pickup_data, metro_distance: float, positive: bool) -> None:
    features, points = pickup_data
    features = features.copy()
    features["metro_dist_m"] = 1500
    features.loc[0, "metro_dist_m"] = metro_distance
    parameters = {
        "visits_per_resident_month": 2,
        "visits_per_worker_month": 6,
        "avg_check_rub": 300,
        "metro_visits_per_month": 1000,
        "metro_influence_distance_m": 300,
        "transit_visits_per_stop_month": 0,
        "max_walk_distance_m": 800,
        "distance_decay_beta": 2,
        "outside_option_weight": 1,
    }
    model = prepare_model(features, points, "coffee", 800)
    baseline = float(model.revenue(parameters)[0])
    factors = explain_factors(
        model, 0, features, points, np.zeros(len(features)), 0, pd.DataFrame([parameters]), baseline
    )
    metro = next(factor for factor in factors[:5] if factor.code == "metro_dist_m")
    assert (metro.effect_rub > 0) == positive
    if not positive:
        assert metro.effect_rub == pytest.approx(0)
