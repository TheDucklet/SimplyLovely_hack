from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from geostart.api.main import app
from geostart.config import get_city
from geostart.economics import service
from geostart.economics.sensitivity import median_payback
from geostart.pipeline.fixtures import write_fixtures
from geostart.schemas_v2 import EconomicsRequest

client = TestClient(app)
PATH = "/api/v2/sensitivity"


@pytest.fixture(scope="module")
def tula_data(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("sensitivity")
    write_fixtures("tula", root / "processed" / "tula")
    return root


@pytest.fixture(autouse=True)
def data_mode(tula_data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(tula_data))
    monkeypatch.setenv("GEOSTART_USE_MOCKS", "false")


def request_payload() -> dict:
    lat, lon = get_city("tula").center
    return {
        "city": "tula",
        "niche": "coffee",
        "demand": {"source": "geostart", "lat": lat, "lon": lon},
        "financing": {"loan_share": 0.5},
        "start_month": 1,
        "start_year": 2027,
    }


def test_factors_and_stresses_use_sorted_scenario_medians() -> None:
    response = client.post(PATH, json=request_payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["versions"]["model"] == "economics-0.3.0"
    assert body["shift_share"] == 0.2
    factors = {factor["code"]: factor for factor in body["factors"]}
    assert len(body["factors"]) == 5
    assert set(factors) == {"revenue", "rent", "wages", "cogs_share", "capex"}
    profit = "profit_steady_month_p50"
    spread = [abs(factor["high"][profit] - factor["low"][profit]) for factor in factors.values()]
    assert spread == sorted(spread, reverse=True)
    for factor in factors.values():
        assert factor["low"]["change"] == -0.2
        assert factor["high"]["change"] == 0.2
    base = body["base"]
    assert factors["revenue"]["low"][profit] < base[profit] < factors["revenue"]["high"][profit]
    assert factors["rent"]["high"][profit] < base[profit] < factors["rent"]["low"][profit]
    stresses = {stress["code"]: stress for stress in body["stresses"]}
    assert len(body["stresses"]) == 4
    assert set(stresses) == {"revenue_minus_20", "rent_plus_15", "rate_plus_3", "combined"}
    assert stresses["revenue_minus_20"][profit] < base[profit]
    assert stresses["revenue_minus_20"][profit] == factors["revenue"]["low"][profit]
    for scenario in (base, *stresses.values()):
        assert 0 <= scenario["probability_no_payback_24"] <= 1


def test_identical_requests_reuse_one_demand_calculation_each(monkeypatch: pytest.MonkeyPatch) -> None:
    resolve = Mock(wraps=service.resolve_demand)
    monkeypatch.setattr(service, "resolve_demand", resolve)
    payload = request_payload()
    payload["shift_share"] = 0.35
    first = client.post(PATH, json=payload)
    second = client.post(PATH, json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert resolve.call_count == 2


def test_shift_share_above_limit_uses_problem_json() -> None:
    payload = request_payload()
    payload["shift_share"] = 0.7
    response = client.post(PATH, json=payload)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["errors"][0]["field"] == "shift_share"


def test_revenue_source_works_without_geo_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(tmp_path))
    payload = {
        "city": "tula",
        "niche": "coffee",
        "demand": {"source": "revenue", "revenue_month": {"p10": 500000, "p50": 800000, "p90": 1000000}},
        "operations": {"salary_rub_month": 50000},
        "start_month": 1,
        "start_year": 2027,
    }
    response = client.post(PATH, json=payload)
    assert response.status_code == 200, response.text
    assert len(response.json()["factors"]) == 5


def test_mock_demand_preserves_requested_shift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOSTART_USE_MOCKS", "true")
    payload = request_payload()
    payload["shift_share"] = 0.15
    response = client.post(PATH, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["shift_share"] == 0.15


def test_loan_rate_stress_increases_interest_by_adjusting_loan_terms() -> None:
    request = EconomicsRequest.model_validate(request_payload())
    base = service.calculate(request)
    stress = service.calculate(
        request, adjustments=service.Adjustments(loan_rate_add=0.03), demand=base.demand
    )
    assert stress.settings.loan_terms.rate_annual == pytest.approx(
        base.settings.loan_terms.rate_annual + 0.03
    )
    assert stress.projection.interest.sum() > base.projection.interest.sum()


@pytest.mark.parametrize(
    ("months", "expected"),
    [([10, 13, 15, np.nan], 14), ([10, 13, np.nan, np.nan], 13), ([10, np.nan, np.nan, np.nan], None)],
)
def test_median_payback_includes_the_unrepaid_scenarios(months: list[float], expected: float | None) -> None:
    assert median_payback(np.array(months)) == expected
