from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geostart.api import data_backend
from geostart.api.main import app
from geostart.config import get_city
from geostart.model import score_city
from geostart.pipeline.fixtures import build_addresses, write_fixtures

client = TestClient(app)


@pytest.fixture(scope="module")
def data_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("data")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GEOSTART_DATA_DIR", str(root))
        write_fixtures("tula", root / "processed" / "tula")
        for niche in ("coffee", "pickup_point"):
            score_city("tula", niche)
    return root


@pytest.fixture(autouse=True)
def data_mode(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(data_root))
    monkeypatch.setenv("GEOSTART_USE_MOCKS", "false")
    data_backend.read_parquet_version.cache_clear()


def test_health_reports_data_mode() -> None:
    body = client.get("/api/v1/health").json()
    assert body["mode"] == "data"
    assert body["data_version"] == "2026-10-15"


def test_hexes_come_from_city_scores(data_root: Path) -> None:
    body = client.get("/api/v1/hexes", params={"city": "tula", "niche": "coffee"}).json()
    scores = data_backend.read_parquet_version(
        str(data_root / "scores" / "tula_coffee.parquet"),
        (data_root / "scores" / "tula_coffee.parquet").stat().st_mtime_ns,
    )
    assert len(body["items"]) == len(scores)
    assert all(item["payback_months_p50"] is None or item["payback_months_p50"] > 0 for item in body["items"])


def test_city_without_scores_returns_404_with_hint() -> None:
    response = client.get("/api/v1/hexes", params={"city": "moscow", "niche": "coffee"})
    assert response.status_code == 404
    assert "geostart.model score --city moscow" in response.json()["detail"]


def test_competitors_have_no_nan_brands() -> None:
    body = client.get("/api/v1/competitors", params={"city": "tula", "niche": "coffee"}).json()
    assert body
    assert all(item["brand"] is None or isinstance(item["brand"], str) for item in body)


def test_search_matches_all_tokens_and_ignores_yo() -> None:
    address = build_addresses("tula")["address"].iloc[0]
    street, house = address.rsplit(", ", 1)
    body = client.get("/api/v1/search", params={"city": "tula", "q": f"{street.lower()} {house}"}).json()
    assert body[0]["address"].startswith(street)
    assert all(house in match["address"] for match in body)
    assert client.get("/api/v1/search", params={"city": "tula", "q": "Тестовая"}).json()


def test_report_uses_model() -> None:
    city = get_city("tula")
    payload = {"city": "tula", "niche": "coffee", "lat": city.center[0], "lon": city.center[1], "area_m2": 40}
    response = client.post("/api/v1/report", json=payload)
    assert response.status_code == 200
    report = response.json()
    assert report["revenue_month"]["p10"] <= report["revenue_month"]["p50"] <= report["revenue_month"]["p90"]
    assert report["assumptions"]


def test_report_outside_city_is_rejected() -> None:
    payload = {"city": "tula", "niche": "coffee", "lat": 59.93, "lon": 30.31}
    response = client.post("/api/v1/report", json=payload)
    assert response.status_code == 422
    assert "вне границ" in response.json()["detail"]


def test_exact_house_number_comes_first() -> None:
    addresses = build_addresses("tula")
    target = addresses[addresses["address"].str.endswith(", 7")]["address"].iloc[0]
    street = target.rsplit(", ", 1)[0]
    body = client.get("/api/v1/search", params={"city": "tula", "q": f"{street} 7"}).json()
    assert body[0]["address"] == target


def test_large_responses_are_compressed() -> None:
    response = client.get(
        "/api/v1/hexes", params={"city": "tula", "niche": "coffee"}, headers={"Accept-Encoding": "gzip"}
    )
    assert response.headers.get("content-encoding") == "gzip"


def test_warmup_prepares_loaded_cities_and_skips_missing() -> None:
    durations = data_backend.warm_model_cache()
    assert set(durations) == {"tula_coffee", "tula_pickup_point"}


def test_startup_with_warmup_serves_reports() -> None:
    with TestClient(app) as warmed:
        response = warmed.get("/api/v1/health")
    assert response.status_code == 200
