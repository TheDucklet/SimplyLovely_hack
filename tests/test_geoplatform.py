from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from geostart.api import data_backend
from geostart.api.main import app
from geostart.config import get_city
from geostart.economics.geoplatform import SQUARE_SIZE_M, SquareGrid, stub_path
from geostart.economics.geoplatform_stub import main as build_stub
from geostart.model.demand import distances_m
from geostart.pipeline.fixtures import write_fixtures

client = TestClient(app)
PROBLEM = "application/problem+json"


@pytest.fixture(scope="module")
def data_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("data")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GEOSTART_DATA_DIR", str(root))
        write_fixtures("tula", root / "processed" / "tula")
        build_stub(["--city", "tula"])
    return root


@pytest.fixture(autouse=True)
def data_mode(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(data_root))
    monkeypatch.setenv("GEOSTART_USE_MOCKS", "false")
    data_backend.read_parquet_version.cache_clear()


def platform_request(niche: str = "coffee", **demand: object) -> dict:
    center = get_city("tula").center
    return {
        "city": "tula",
        "niche": niche,
        "demand": {"source": "geoplatform", "lat": center[0], "lon": center[1], **demand},
        "start_year": 2027,
        "start_month": 1,
    }


def covering_square(spend: float) -> dict:
    lat, lon = get_city("tula").center
    return {
        "square_id": "centre",
        "south": lat - 0.05,
        "west": lon - 0.08,
        "north": lat + 0.05,
        "east": lon + 0.08,
        "spend_rub_month": {"p10": spend * 0.8, "p50": spend, "p90": spend * 1.2},
        "footfall_day": {"p10": 800, "p50": 1000, "p90": 1200},
    }


def test_square_grid_has_500_metre_cells() -> None:
    latitudes = np.array([54.19, 54.20])
    longitudes = np.array([37.61, 37.62])
    grid = SquareGrid.around(latitudes, longitudes)
    south, west, north, east = grid.bounds(0, 0)
    height = distances_m(np.array([[south, west]]), np.array([[north, west]]))[0]
    width = distances_m(np.array([[south, west]]), np.array([[south, east]]))[0]
    assert height == pytest.approx(SQUARE_SIZE_M, rel=0.01)
    assert width == pytest.approx(SQUARE_SIZE_M, rel=0.01)
    rows, columns = grid.indices(latitudes, longitudes)
    assert (rows >= 0).all() and (columns >= 0).all()


def test_stub_layers_cover_visit_niches_only(data_root: Path) -> None:
    layers = pd.read_parquet(stub_path("tula"))
    assert len(layers) > 0
    assert "spend_coffee_p50" in layers and "spend_grocery_p50" in layers
    assert "spend_pickup_point_p50" not in layers
    assert (layers.spend_coffee_p10 <= layers.spend_coffee_p50).all()
    assert (layers.spend_coffee_p50 <= layers.spend_coffee_p90).all()
    assert (layers.south < layers.north).all()


def test_stub_source_runs_through_unchanged_engine() -> None:
    response = client.post("/api/v2/economics", json=platform_request())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["demand"]["source"] == "geoplatform"
    assert body["demand"]["provider"] == "заглушка геоплатформы банка"
    assert body["demand"]["revenue_steady_month"]["p50"] > 0
    assert body["scenarios"] == 200
    assert any(item["name"].startswith("Квадратов геоплатформы") for item in body["assumptions"])


def test_request_squares_scale_revenue() -> None:
    small = client.post("/api/v2/economics", json=platform_request(squares=[covering_square(100_000)])).json()
    large = client.post("/api/v2/economics", json=platform_request(squares=[covering_square(200_000)])).json()
    ratio = large["demand"]["revenue_steady_month"]["p50"] / small["demand"]["revenue_steady_month"]["p50"]
    assert ratio == pytest.approx(2.0, rel=0.01)
    assert small["demand"]["provider"] is None


def test_same_point_differs_only_in_demand() -> None:
    model = client.post(
        "/api/v2/economics",
        json={**platform_request(), "demand": {**platform_request()["demand"], "source": "geostart"}},
    ).json()
    platform = client.post("/api/v2/economics", json=platform_request()).json()
    assert model["investment"]["capex"] == pytest.approx(platform["investment"]["capex"])
    assert model["demand"]["district"] == platform["demand"]["district"]
    assert model["versions"] == platform["versions"]


def test_pickup_point_is_rejected() -> None:
    response = client.post("/api/v2/economics", json=platform_request("pickup_point"))
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM)
    assert "пункта выдачи" in response.json()["detail"]


def test_squares_far_from_point_are_rejected() -> None:
    far = covering_square(100_000)
    far.update(south=10.0, north=10.1, west=10.0, east=10.1)
    response = client.post("/api/v2/economics", json=platform_request(squares=[far]))
    assert response.status_code == 422
    assert "нет ячеек" in response.json()["detail"]


def test_inverted_square_bounds_are_rejected() -> None:
    square = covering_square(100_000)
    square["south"], square["north"] = square["north"], square["south"]
    response = client.post("/api/v2/economics", json=platform_request(squares=[square]))
    assert response.status_code == 422
    assert "south < north" in response.json()["detail"]
