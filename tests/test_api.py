import pytest
from fastapi.testclient import TestClient

from geostart.api.main import app
from geostart.config import get_city

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOSTART_USE_MOCKS", "true")


def test_health_reports_mock_mode() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "mocks"


def test_cities_follow_config() -> None:
    body = client.get("/api/v1/cities").json()
    assert [city["code"] for city in body] == ["moscow", "tula"]
    assert body[0] == {"code": "moscow", "name": "Москва", "center": [55.7558, 37.6176], "zoom": 11}


def test_niches_follow_config() -> None:
    body = client.get("/api/v1/niches").json()
    assert body == [
        {"code": "coffee", "name": "Кофейня"},
        {"code": "pickup_point", "name": "Пункт выдачи заказов"},
    ]


@pytest.mark.parametrize("niche", ["coffee", "pickup_point"])
def test_hexes_cover_city_grid(niche: str) -> None:
    body = client.get("/api/v1/hexes", params={"city": "tula", "niche": niche}).json()
    assert body["city"] == "tula"
    assert len(body["items"]) > 1000
    assert {item["risk_level"] for item in body["items"]} <= {"low", "medium", "high"}


def test_competitors_have_contract_fields() -> None:
    body = client.get("/api/v1/competitors", params={"city": "moscow", "niche": "coffee"}).json()
    assert body
    assert set(body[0]) == {"name", "brand", "lat", "lon", "source"}


def test_search_returns_at_most_ten_matches() -> None:
    body = client.get("/api/v1/search", params={"city": "moscow", "q": "Тестовая"}).json()
    assert 0 < len(body) <= 10
    assert all("Тестовая" in match["address"] for match in body)


def test_report_is_consistent() -> None:
    city = get_city("moscow")
    payload = {
        "city": "moscow",
        "niche": "coffee",
        "lat": city.center[0],
        "lon": city.center[1],
        "area_m2": 40,
    }
    response = client.post("/api/v1/report", json=payload)
    assert response.status_code == 200
    report = response.json()
    revenue = report["revenue_month"]
    assert revenue["p10"] <= revenue["p50"] <= revenue["p90"]
    costs = report["costs_month"]
    parts = costs["rent"] + costs["payroll"] + costs["cogs"] + costs["taxes"] + costs["other"]
    assert abs(costs["total"] - parts) <= 5
    assert report["profit_month_p50"] == pytest.approx(revenue["p50"] - costs["total"], abs=5)
    if report["profit_month_p50"] <= 0:
        assert report["payback_months_p50"] is None


def test_report_outside_city_is_rejected_in_russian() -> None:
    payload = {"city": "moscow", "niche": "coffee", "lat": 59.93, "lon": 30.31}
    response = client.post("/api/v1/report", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"] == "Точка вне границ города moscow, выберите место внутри МКАД"


def test_unknown_city_returns_404() -> None:
    response = client.get("/api/v1/hexes", params={"city": "kazan", "niche": "coffee"})
    assert response.status_code == 404
    assert "Город kazan не найден" in response.json()["detail"]
