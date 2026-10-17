import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from geostart.model.demand import cell_demand, competitor_attractiveness, prepare_model
from geostart.model.validation import edge_weights, point_simulation
from geostart.pipeline.fixtures import write_fixtures

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "recheck.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("recheck", SCRIPT_PATH)
recheck = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(recheck)

PARAMETERS = {
    "visits_per_resident_month": 2.0,
    "visits_per_worker_month": 6.0,
    "avg_check_rub": 330.0,
    "max_walk_distance_m": 500.0,
    "distance_decay_beta": 2.0,
    "outside_option_weight": 1.0,
}


@pytest.fixture
def seat_data(tmp_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    write_fixtures("moscow", tmp_path)
    features = pd.read_parquet(tmp_path / "hex_features.parquet").iloc[:19].reset_index(drop=True)
    points = pd.DataFrame(
        {
            "poi_id": [f"point-{index}" for index in range(6)],
            "h3": [features.iloc[index // 2].h3 for index in range(6)],
            "source": "mos_ru",
            "niche": "coffee",
            "seats": [0, 6, 20, 50, 80, 182],
        }
    )
    return features, points


@pytest.mark.parametrize("scale,expected", [(10, [1, 1.6, 6]), (20, [1, 1.3, 3.5]), (40, [1, 1.15, 2.25])])
def test_seat_experiments_keep_production_formula_and_input(scale: float, expected: list[float]) -> None:
    points = pd.DataFrame({"source": ["mos_ru", "mos_ru", "mos_ru", "osm"], "seats": [0, 6, 50, 100]})
    unchanged = points.copy(deep=True)
    changed = recheck.competitors_for_scale(points, scale)
    np.testing.assert_allclose(competitor_attractiveness(changed), [*expected, 1])
    pd.testing.assert_frame_equal(points, unchanged)


def test_legacy_reconstruction_preserves_colocated_osm_points(seat_data) -> None:
    _, points = seat_data
    labels = points[["poi_id", "h3"]]
    rebuilt = recheck.legacy_osm_points(labels)
    assert rebuilt.poi_id.tolist() == labels.poi_id.tolist()
    assert rebuilt.h3.value_counts().equals(labels.h3.value_counts())
    np.testing.assert_array_equal(competitor_attractiveness(rebuilt), np.ones(len(points)))


def test_binary_comparison_uses_same_controls_across_models_and_labels() -> None:
    features = pd.DataFrame({"h3": [f"cell-{index}" for index in range(10)]})
    old = pd.DataFrame({"h3": ["cell-8"]})
    new = pd.DataFrame({"h3": ["cell-8", "cell-9"]})
    results = recheck.binary_label_comparison(features, old, new, np.arange(10)[::-1], np.arange(10))
    assert len(results) == 4
    assert {row["controls"] for row in results} == {1}
    assert [row["positive_cells"] for row in results] == [1, 2, 1, 2]
    assert [row["roc_auc"] for row in results] == [0, 0, 1, 1]
    assert [row["lift"] for row in results] == [0, 0, 5, 5]


def test_many_seat_values_match_direct_removal(seat_data) -> None:
    features, points = seat_data
    model = prepare_model(features, points, "coffee", 500)
    samples = pd.DataFrame([PARAMETERS])
    simulated = point_simulation(model, points, samples)
    for index, point in points.iterrows():
        reduced = prepare_model(features, points.drop(index=index), "coffee", 500)
        cell_index = int(np.flatnonzero(features.h3.eq(point.h3))[0])
        assert simulated.revenues[0, index] == pytest.approx(reduced.revenue(PARAMETERS)[cell_index])


def test_actual_point_allocation_conserves_city_demand(seat_data) -> None:
    features, points = seat_data
    model = prepare_model(features, points, "coffee", 500)
    actual = point_simulation(model, points, pd.DataFrame([PARAMETERS]), competitor_attractiveness(points))
    weights = edge_weights(model, PARAMETERS)
    pressure = np.bincount(
        model.origin_indices,
        weights=weights * model.attraction[model.destination_indices],
        minlength=len(features),
    )
    demand = cell_demand(features, "coffee", PARAMETERS)
    expected = np.sum(demand * pressure / (pressure + PARAMETERS["outside_option_weight"]))
    assert actual.revenues.sum() == pytest.approx(expected)
    assert np.all(actual.revenues <= actual.reachable_demand)


def test_seat_scenarios_change_one_point_at_a_time(seat_data) -> None:
    features, points = seat_data
    model = prepare_model(features, points, "coffee", 500)
    base = point_simulation(model, points, pd.DataFrame([PARAMETERS]))
    attractions = np.ones(len(points))
    attractions[0] = 3.5
    larger = point_simulation(model, points, pd.DataFrame([PARAMETERS]), attractions)
    assert larger.revenues[0, 0] > base.revenues[0, 0]
    np.testing.assert_allclose(larger.revenues[:, 1:], base.revenues[:, 1:])


def test_baseline_paths_resolve_against_current_data_root(tmp_path: Path, monkeypatch) -> None:
    directory = write_fixtures("moscow", tmp_path / "current")
    monkeypatch.setattr(recheck, "city_directory", lambda city: directory)
    data_file = directory / "competitors.parquet"
    digest = hashlib.sha256(data_file.read_bytes()).hexdigest()
    manifest = tmp_path / "old_manifest.json"
    key = "C:/old-data/processed/moscow/competitors.parquet"
    manifest.write_text(json.dumps({key: digest}), encoding="utf-8")
    assert recheck.input_changes_since_baseline(manifest) == []
    manifest.write_text(json.dumps({key: "different"}), encoding="utf-8")
    assert recheck.input_changes_since_baseline(manifest) == ["moscow/competitors.parquet"]
