from pathlib import Path

import h3
import numpy as np
import pandas as pd
import pytest

from geostart.model.demand import prepare_model, sample_parameters
from geostart.model.factors import bounded_competition_effect, competition_reference
from geostart.model.validation import (
    leave_one_out_potentials,
    pickup_decomposition,
    roc_auc,
    validation_metrics,
)
from geostart.model.validation_run import verify_baseline_inputs
from geostart.pipeline.fixtures import write_fixtures

PARAMETERS = {
    "visits_per_resident_month": 2.0,
    "visits_per_worker_month": 6.0,
    "avg_check_rub": 330.0,
    "orders_per_resident_month": 3.5,
    "marketplace_share": 0.35,
    "payout_per_order_rub": 18.0,
    "max_walk_distance_m": 500.0,
    "distance_decay_beta": 3.0,
    "outside_option_weight": 1.0,
}


@pytest.fixture
def city_data(tmp_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    write_fixtures("moscow", tmp_path)
    features = pd.read_parquet(tmp_path / "hex_features.parquet")
    cell = h3.latlng_to_cell(55.7558, 37.6176, 9)
    features = features.loc[features.h3.isin(h3.grid_disk(cell, 2))].reset_index(drop=True)
    cells = [features.iloc[0].h3, features.iloc[0].h3, features.iloc[1].h3]
    coordinates = np.array([h3.cell_to_latlng(item) for item in cells])
    competitors = pd.DataFrame(
        {
            "poi_id": ["one", "two", "three"],
            "h3": cells,
            "source": ["osm", "mos_ru", "osm"],
            "seats": [None, 20, None],
            "niche": "coffee",
            "lat": coordinates[:, 0],
            "lon": coordinates[:, 1],
        }
    )
    return features, competitors


@pytest.mark.parametrize("district_size,expected", [(29, 0), (30, 12)])
def test_competition_reference_uses_district_from_thirty_cells(district_size: int, expected: float) -> None:
    features = pd.DataFrame({"district": ["Центр"] * district_size + ["Окраина"] * 100})
    counts = np.array([12] * district_size + [0] * 100)
    assert competition_reference(features, counts, "Центр") == expected


@pytest.mark.parametrize(
    "revenue,counterfactual,expected", [(100, 1000, -100), (100, 0, 100), (0, 1000, 0), (100, 80, 20)]
)
def test_competition_effect_cannot_exceed_cell_revenue(
    revenue: float, counterfactual: float, expected: float
) -> None:
    assert bounded_competition_effect(revenue, counterfactual) == expected


def test_pickup_default_is_near_zero_and_explicit_research_wins() -> None:
    ranges = {
        name: {"p10": value, "p90": value}
        for name, value in PARAMETERS.items()
        if name != "outside_option_weight"
    }
    pickup = sample_parameters("pickup_point", ranges)
    coffee = sample_parameters("coffee", ranges)
    assert pickup.outside_option_weight.between(0, 0.000002).all()
    assert coffee.outside_option_weight.between(0.5, 1.5).all()
    ranges["outside_option_weight"] = {"p10": 0.25, "p90": 0.25}
    assert sample_parameters("pickup_point", ranges).outside_option_weight.eq(0.25).all()


def test_zero_pickup_alternative_is_finite_and_can_capture_own_cell(city_data) -> None:
    features, competitors = city_data
    model = prepare_model(features, competitors.iloc[:0], "pickup_point", 500)
    parameters = {**PARAMETERS, "outside_option_weight": 0.0, "max_walk_distance_m": 1.0}
    revenue = model.revenue(parameters)
    expected = features.residents.to_numpy() * 3.5 * 0.35 * 18
    np.testing.assert_allclose(revenue, expected)
    assert np.isfinite(revenue).all()


def test_vectorized_leave_one_out_matches_removing_each_point(city_data) -> None:
    features, competitors = city_data
    samples = pd.DataFrame([PARAMETERS, {**PARAMETERS, "distance_decay_beta": 2.0}])
    model = prepare_model(features, competitors, "coffee", 500)
    potentials = leave_one_out_potentials(model, competitors, samples)
    for point_index, point in competitors.iterrows():
        remaining = competitors.drop(index=point_index)
        reduced = prepare_model(features, remaining, "coffee", 500)
        cell_index = int(np.flatnonzero(features.h3.eq(point.h3))[0])
        expected = np.median(
            [reduced.revenue(parameters)[cell_index] for parameters in samples.to_dict("records")]
        )
        assert potentials[point_index] == pytest.approx(expected)


def test_auc_accounts_for_ties() -> None:
    assert roc_auc(np.array([3, 4]), np.array([1, 2])) == 1
    assert roc_auc(np.array([1, 1]), np.array([1, 1])) == 0.5
    assert roc_auc(np.array([1, 2]), np.array([3, 4])) == 0


def test_metrics_keep_each_point_and_sample_empty_controls() -> None:
    features = pd.DataFrame({"h3": [f"cell-{index}" for index in range(10)]})
    competitors = pd.DataFrame({"poi_id": ["one", "two"], "h3": ["cell-9", "cell-9"], "niche": "coffee"})
    metrics, observations = validation_metrics(
        features, competitors, "coffee", np.arange(10, dtype=float), np.array([12.0, 12.0]), seed=2026
    )
    assert metrics["points"] == 2
    assert metrics["occupied_cells"] == 1
    assert metrics["roc_auc"] == 1
    assert metrics["top20_share"] == 1
    assert metrics["lift"] == 5
    assert len(observations) == 2


def test_pickup_decomposition_multiplies_to_model_revenue(city_data) -> None:
    features, competitors = city_data
    model = prepare_model(features, competitors.iloc[:0], "pickup_point", 500)
    result = pickup_decomposition(model, PARAMETERS, 0)
    product = (
        result["residents_catchment"]
        * result["orders_per_resident_month"]
        * result["marketplace_share"]
        * result["payout_per_order_rub"]
        * result["conditional_huff_share"]
        * (1 - result["outside_share"])
    )
    assert product == pytest.approx(result["revenue"])
    assert product == pytest.approx(model.revenue(PARAMETERS)[0])


def test_saved_baseline_rejects_changed_inputs(tmp_path: Path, monkeypatch) -> None:
    from geostart.model import validation_run

    for city in ("moscow", "tula"):
        directory = tmp_path / city
        write_fixtures(city, directory)
    research = tmp_path / "research"
    research.mkdir()
    parameter = research / "parameters.yaml"
    parameter.write_text("status: placeholder", encoding="utf-8")
    monkeypatch.setattr(validation_run, "city_directory", lambda city: tmp_path / city)
    monkeypatch.setattr(validation_run.settings, "research_dir", lambda: research)
    output = tmp_path / "validation"
    output.mkdir()
    verify_baseline_inputs(output)
    verify_baseline_inputs(output)
    parameter.write_text("status: reviewed", encoding="utf-8")
    with pytest.raises(ValueError, match="изменились"):
        verify_baseline_inputs(output)
