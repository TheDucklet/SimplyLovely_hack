from pathlib import Path

import h3
import numpy as np
import pandas as pd
import pytest

from geostart.model.assumptions import demand_assumptions, resolve_rent, wage_assumptions
from geostart.model.data import load_demand_inputs, scores_directory
from geostart.model.demand import (
    cell_demand,
    competitor_attractiveness,
    distances_m,
    prepare_model,
    sample_parameters,
    simulate_demand,
)
from geostart.pipeline.fixtures import write_fixtures

PARAMETERS = {
    "visits_per_resident_month": 2.0,
    "visits_per_worker_month": 6.0,
    "avg_check_rub": 330.0,
    "orders_per_resident_month": 3.5,
    "marketplace_share": 0.35,
    "payout_per_order_rub": 18.0,
    "max_walk_distance_m": 500.0,
    "distance_decay_beta": 2.0,
    "outside_option_weight": 1.0,
}


@pytest.fixture
def city_data(tmp_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    write_fixtures("tula", tmp_path)
    return pd.read_parquet(tmp_path / "hex_features.parquet"), pd.read_parquet(
        tmp_path / "competitors.parquet"
    )


def test_cell_demand_uses_jobs_and_pickup_ignores_jobs(city_data) -> None:
    features, _ = city_data
    features = features.iloc[:1].assign(residents=100, workers=50)
    assert cell_demand(features, "coffee", PARAMETERS)[0] == 165000
    assert cell_demand(features, "pickup_point", PARAMETERS)[0] == pytest.approx(2205)


def test_outside_alternative_and_colocated_competitor_split_demand(city_data) -> None:
    features, competitors = city_data
    features = features.iloc[:1]
    empty = competitors.iloc[:0]
    demand = cell_demand(features, "coffee", PARAMETERS)[0]
    alone = prepare_model(features, empty, "coffee", 500).revenue(PARAMETERS)[0]
    assert alone == pytest.approx(demand / 2)
    competitor = competitors.iloc[:1].assign(h3=features.iloc[0]["h3"], niche="coffee", source="osm")
    shared = prepare_model(features, competitor, "coffee", 500).revenue(PARAMETERS)[0]
    assert shared == pytest.approx(demand / 3)
    assert prepare_model(features, empty, "coffee", 500).revenue(
        {**PARAMETERS, "outside_option_weight": 2.0}
    )[0] == pytest.approx(demand / 3)


def test_only_mos_ru_seats_increase_attraction() -> None:
    competitors = pd.DataFrame(
        {"source": ["osm", "mos_ru", "mos_ru", "mos_ru"], "seats": [100, None, 20, 40]}
    )
    np.testing.assert_array_equal(competitor_attractiveness(competitors), [1, 1, 2, 3])


@pytest.mark.parametrize("niche", ["coffee", "pickup_point"])
def test_sparse_huff_matches_independent_all_pairs_reference(city_data, niche: str) -> None:
    features, competitors = city_data
    center = features.iloc[len(features) // 2]["h3"]
    features = features.loc[features["h3"].isin(h3.grid_disk(center, 3))].reset_index(drop=True)
    competitors = competitors.iloc[:8].copy()
    competitors["h3"] = features["h3"].iloc[:8].to_list()
    competitors["niche"] = niche
    outside_cell = next(cell for cell in h3.grid_disk(center, 4) if cell not in set(features["h3"]))
    competitors.loc[competitors.index[0], "h3"] = outside_cell
    parameters = {**PARAMETERS, "max_walk_distance_m": 800}
    model = prepare_model(features, competitors, niche, 800)
    feature_centers = np.array([h3.cell_to_latlng(cell) for cell in features["h3"]])
    competitor_centers = np.array([h3.cell_to_latlng(cell) for cell in competitors["h3"]])
    expected = np.zeros(len(features))
    demand = cell_demand(features, niche, parameters)
    for origin, coordinate in enumerate(feature_centers):
        competitor_distances = distances_m(np.tile(coordinate, (len(competitors), 1)), competitor_centers)
        competitor_weights = np.maximum(competitor_distances / 100, 1) ** -2
        pressure = np.sum(
            competitor_weights * (competitor_distances <= 800) * competitor_attractiveness(competitors)
        )
        candidate_distances = distances_m(np.tile(coordinate, (len(features), 1)), feature_centers)
        weights = np.maximum(candidate_distances / 100, 1) ** -2 * (candidate_distances <= 800)
        expected += demand[origin] * weights / (weights + pressure + 1)
    np.testing.assert_allclose(model.revenue(parameters), expected)


def test_distance_cutoff_and_decay(city_data) -> None:
    features, competitors = city_data
    center = features.iloc[0]["h3"]
    neighbor = next(cell for cell in h3.grid_disk(center, 1) if cell != center)
    features = pd.concat([features.iloc[:1], features.iloc[:1]], ignore_index=True)
    features["h3"] = [center, neighbor]
    features["residents"] = [100, 0]
    features["workers"] = 0
    model = prepare_model(features, competitors.iloc[:0], "coffee", 500)
    near = model.revenue({**PARAMETERS, "max_walk_distance_m": 1})
    assert near[1] == 0
    mild = model.revenue(PARAMETERS)
    steep = model.revenue({**PARAMETERS, "distance_decay_beta": 4})
    assert 0 < steep[1] < mild[1]


def test_simulation_is_reproducible_and_handles_missing_metro(city_data) -> None:
    features, competitors = city_data
    features = features.iloc[:12]
    ranges = {name: {"p10": value, "p90": value * 1.1} for name, value in PARAMETERS.items()}
    first = simulate_demand(features, competitors, "coffee", ranges, runs=20)
    pd.testing.assert_frame_equal(first, simulate_demand(features, competitors, "coffee", ranges, runs=20))
    assert np.isfinite(first.filter(like="revenue")).all().all()
    assert first["revenue_p10"].le(first["revenue_p50"]).all()
    assert first["revenue_p50"].le(first["revenue_p90"]).all()
    samples = sample_parameters("coffee", ranges, runs=200)
    for name in samples:
        assert samples[name].between(ranges[name]["p10"], ranges[name]["p90"]).all()
    assert not first.equals(simulate_demand(features, competitors, "coffee", ranges, runs=20, seed=1))


@pytest.mark.parametrize("runs", [0, -1, True, 1.5])
def test_invalid_run_count_is_rejected(runs) -> None:
    with pytest.raises(ValueError, match="Число прогонов"):
        sample_parameters("coffee", {}, runs=runs)


def test_proxy_salary_and_missing_rent_are_explained() -> None:
    wages = pd.DataFrame({"profession": ["barista"], "basis": ["proxy"], "salary_p50": [42500]})
    assert wage_assumptions(wages, "barista")[0].value == 42500
    rents = pd.DataFrame({"zone": ["А", "Б"], "rent_rub_m2_month_p50": [4000, 7000]})
    assert resolve_rent(rents, "А") == (4000, [])
    rent, assumptions = resolve_rent(rents, "В")
    assert rent == 5500
    assert "медиане" in assumptions[0].name
    assert len(demand_assumptions({"status": "placeholder", "demand": {}})) == 4


@pytest.mark.parametrize(
    "name,value", [("outside_option_weight", 0), ("distance_decay_beta", -1), ("avg_check_rub", float("nan"))]
)
def test_invalid_parameters_are_rejected(city_data, name: str, value: float) -> None:
    features, competitors = city_data
    model = prepare_model(features.iloc[:1], competitors.iloc[:0], "coffee", 500)
    with pytest.raises(ValueError):
        model.revenue({**PARAMETERS, name: value})


def test_constant_ranges_produce_exact_revenue_quantiles(city_data) -> None:
    features, competitors = city_data
    features = features.iloc[:1]
    competitors = competitors.iloc[:0]
    ranges = {name: {"p10": value, "p90": value} for name, value in PARAMETERS.items()}
    result = simulate_demand(features, competitors, "pickup_point", ranges, runs=3)
    expected = cell_demand(features, "pickup_point", PARAMETERS)[0] / 2
    np.testing.assert_allclose(result.filter(like="revenue"), expected)


def test_range_endpoints_are_validated_before_sampling() -> None:
    ranges = {name: {"p10": value, "p90": value} for name, value in PARAMETERS.items()}
    ranges["outside_option_weight"] = {"p10": 0, "p90": 1}
    with pytest.raises(ValueError, match="положительным"):
        sample_parameters("coffee", ranges, runs=1)


def test_model_reads_environment_data_directory(tmp_path: Path, monkeypatch) -> None:
    directory = tmp_path / "processed" / "tula"
    write_fixtures("tula", directory)
    (directory / "boundary.geojson").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(tmp_path))
    features, competitors = load_demand_inputs("tula")
    assert len(features) > 0
    assert len(competitors) > 0
    assert scores_directory() == tmp_path / "scores"


def test_explicit_data_directory_overrides_environment(tmp_path: Path, monkeypatch) -> None:
    directory = tmp_path / "processed" / "tula"
    write_fixtures("tula", directory)
    (directory / "boundary.geojson").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(tmp_path / "missing"))
    assert not load_demand_inputs("tula", tmp_path)[0].empty
