import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geostart.api import data_backend
from geostart.api.main import app
from geostart.api.openapi import OPENAPI_V2_PATH, v2_schema
from geostart.config import get_city
from geostart.pipeline.fixtures import write_fixtures

client = TestClient(app)
PROBLEM = "application/problem+json"


@pytest.fixture(scope="module")
def data_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("data")
    write_fixtures("tula", root / "processed" / "tula")
    return root


@pytest.fixture(autouse=True)
def data_mode(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(data_root))
    monkeypatch.setenv("GEOSTART_USE_MOCKS", "false")
    data_backend.read_parquet_version.cache_clear()


def geo_request(**changes: object) -> dict:
    center = get_city("tula").center
    payload = {
        "city": "tula",
        "niche": "coffee",
        "demand": {"source": "geostart", "lat": center[0], "lon": center[1]},
        "start_month": 3,
    }
    payload.update(changes)
    return payload


@pytest.fixture(scope="module")
def geo_report(data_root: Path) -> dict:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GEOSTART_DATA_DIR", str(data_root))
        patch.setenv("GEOSTART_USE_MOCKS", "false")
        response = client.post("/api/v2/economics", json=geo_request(financing={"loan_share": 0.5}))
    assert response.status_code == 200, response.text
    return response.json()


def test_geo_report_has_full_contract(geo_report: dict) -> None:
    assert geo_report["versions"]["model"].startswith("economics-")
    assert geo_report["scenarios"] == 200
    assert len(geo_report["monthly"]) == geo_report["horizon_months"] == 36
    assert len(geo_report["cash_band"]) == 36
    assert [row["year"] for row in geo_report["years"]] == [1, 2, 3]
    assert geo_report["demand"]["source"] == "geostart"
    assert geo_report["demand"]["h3"]
    assert geo_report["monthly"][0]["calendar_month"] == 3
    assert geo_report["tax"]["chosen_automatically"] is True
    assert {option["regime"] for option in geo_report["tax"]["options"]} == {
        "usn_income_6",
        "usn_income_minus_expenses_15",
        "patent",
    }
    assert any(item["name"] == "Источник выручки" for item in geo_report["assumptions"])


def test_auto_regime_has_lowest_taxes(geo_report: dict) -> None:
    eligible = [option for option in geo_report["tax"]["options"] if option["eligible"]]
    best = min(eligible, key=lambda option: option["taxes_horizon_p50"])
    assert geo_report["tax"]["regime"] == best["regime"]


def test_monthly_rows_are_consistent(geo_report: dict) -> None:
    cumulative = -geo_report["investment"]["total"]["p50"]
    for row in geo_report["monthly"]:
        costs = row["cogs"] + row["rent"] + row["payroll"] + row["other"]
        assert row["ebitda"] == pytest.approx(row["revenue"] - costs, abs=0.01)
        assert row["net_profit"] == pytest.approx(row["ebitda"] - row["interest"] - row["taxes"], abs=0.01)
    first = geo_report["monthly"][0]
    second = geo_report["monthly"][1]
    assert second["cumulative_project_cash"] - first["cumulative_project_cash"] == pytest.approx(
        second["ebitda"] - second["taxes"], abs=0.01
    )
    assert cumulative < 0


def test_investment_and_credit_are_consistent(geo_report: dict) -> None:
    investment = geo_report["investment"]
    assert investment["loan"] + investment["own_funds"] == pytest.approx(investment["total"]["p50"], rel=0.05)
    credit = geo_report["credit"]
    assert credit["amount"] == pytest.approx(investment["loan"])
    assert credit["first_payment"] > 0
    assert credit["dscr_threshold"] == 1.25
    assert credit["max_loan_rub"]["p10"] <= credit["max_loan_rub"]["p90"]


def test_report_is_deterministic(geo_report: dict) -> None:
    again = client.post("/api/v2/economics", json=geo_request(financing={"loan_share": 0.5})).json()
    assert again["metrics"] == geo_report["metrics"]


def test_revenue_source_works_without_location() -> None:
    payload = {
        "city": "tula",
        "niche": "pickup_point",
        "demand": {
            "source": "revenue",
            "revenue_month": {"p10": 250000, "p50": 350000, "p90": 500000},
            "provider": "геоплатформа банка",
        },
        "start_month": 1,
    }
    body = client.post("/api/v2/economics", json=payload).json()
    assert body["demand"]["provider"] == "геоплатформа банка"
    assert body["demand"]["revenue_steady_month"]["p50"] == pytest.approx(350000, rel=0.02)
    assert body["metrics"]["unit_name"] == "заказ"
    patent = next(option for option in body["tax"]["options"] if option["regime"] == "patent")
    assert patent["eligible"] is False


def test_traffic_source_multiplies_components() -> None:
    payload = {
        "city": "tula",
        "niche": "coffee",
        "demand": {
            "source": "traffic",
            "visitors_per_day": {"p10": 1000, "p50": 1000, "p90": 1000},
            "conversion": {"p10": 0.05, "p50": 0.05, "p90": 0.05},
            "avg_check_rub": {"p10": 300, "p50": 300, "p90": 300},
        },
        "start_month": 1,
    }
    body = client.post("/api/v2/economics", json=payload).json()
    assert body["demand"]["revenue_steady_month"]["p50"] == pytest.approx(1000 * 0.05 * 300 * 30.4)
    assert body["metrics"]["unit_value_rub"] == 300


def test_user_overrides_replace_research_values() -> None:
    payload = geo_request(
        premises={"area_m2": 50, "rent_rub_m2_month": 1200, "security_deposit_months": 2},
        operations={"staff_count": 3, "salary_rub_month": 55000},
        investment={"capex_rub": 1500000, "working_capital_rub": 0},
        tax={"regime": "usn_income_6"},
    )
    body = client.post("/api/v2/economics", json=payload).json()
    assert body["investment"]["capex"] == 1500000
    assert body["investment"]["security_deposit"] == 50 * 1200 * 2
    assert body["investment"]["working_capital"] == 0
    assert body["steady_month"]["rent"] == 50 * 1200
    assert body["steady_month"]["wages"] == 3 * 55000
    assert body["tax"]["regime"] == "usn_income_6"
    assert body["tax"]["chosen_automatically"] is False


def test_patent_for_company_is_rejected() -> None:
    response = client.post(
        "/api/v2/economics", json=geo_request(tax={"legal_form": "ooo", "regime": "patent"})
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM)
    assert "только ИП" in response.json()["detail"]


def test_validation_errors_use_problem_json() -> None:
    payload = {
        "city": "tula",
        "niche": "coffee",
        "demand": {"source": "revenue", "revenue_month": {"p10": 3, "p50": 2, "p90": 1}},
        "horizon_months": 6,
        "unknown": 1,
    }
    response = client.post("/api/v2/economics", json=payload)
    body = response.json()
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM)
    assert body["title"] == "Некорректные параметры расчёта"
    fields = {item["field"] for item in body["errors"]}
    assert fields == {"demand.revenue_month", "horizon_months", "unknown"}
    assert "p10 ≤ p50 ≤ p90" in body["detail"]


def test_unknown_demand_source_is_explained() -> None:
    response = client.post(
        "/api/v2/economics", json={"city": "tula", "niche": "coffee", "demand": {"source": "radar"}}
    )
    assert response.json()["errors"][0]["message"].startswith("Поле «источник спроса»")


def test_unknown_city_returns_problem_404() -> None:
    response = client.get("/api/v2/norms/coffee", params={"city": "kazan"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM)
    assert response.json()["status"] == 404


def test_v1_errors_keep_old_format() -> None:
    response = client.get("/api/v1/hexes", params={"city": "kazan", "niche": "coffee"})
    assert response.status_code == 404
    assert set(response.json()) == {"detail"}


def test_point_outside_city_is_rejected() -> None:
    payload = geo_request(demand={"source": "geostart", "lat": 59.93, "lon": 30.31})
    response = client.post("/api/v2/economics", json=payload)
    assert response.status_code == 422
    assert "вне границ" in response.json()["detail"]


def test_credit_check_flags_optimistic_plan() -> None:
    payload = {
        "economics": geo_request(),
        "plan": {
            "revenue_month_rub": 50_000_000,
            "capex_rub": 10_000,
            "payback_months": 1,
            "loan_amount_rub": 1_000_000,
        },
    }
    body = client.post("/api/v2/credit-check", json=payload).json()
    assert body["verdict"] == "not_confirmed"
    statuses = {check["code"]: check["status"] for check in body["checks"]}
    assert statuses == {"revenue_month": "above", "capex": "below", "payback_months": "below"}
    assert all(check["risk_flag"] for check in body["checks"])
    assert body["economics"]["credit"]["amount"] == 1_000_000


def test_credit_check_accepts_modest_plan() -> None:
    report = client.post("/api/v2/economics", json=geo_request()).json()
    revenue = report["demand"]["revenue_steady_month"]["p50"]
    payload = {"economics": geo_request(), "plan": {"revenue_month_rub": revenue, "loan_amount_rub": 0}}
    body = client.post("/api/v2/credit-check", json=payload).json()
    assert body["checks"][0]["status"] == "within"
    assert body["probability_dscr_ok"] == 1.0
    assert body["verdict"] == "confirmed"


def test_norms_list_sources_and_parameters() -> None:
    body = client.get("/api/v2/norms/coffee", params={"city": "tula"}).json()
    assert body["unit_name"] == "чек"
    assert body["discount_rate_annual"] == pytest.approx(0.2)
    codes = {item["code"] for item in body["common"]}
    assert {"key_rate_annual", "dscr_threshold"} <= codes
    assert {item["code"] for item in body["parameters"]} == {
        "area_m2",
        "staff_count",
        "cogs_share_of_revenue",
        "other_opex_rub",
        "capex_rub",
    }
    ramp = next(item for item in body["niche_norms"] if item["code"] == "ramp_up_share")
    assert isinstance(ramp["value"], list)


def test_openapi_contract_file_is_current() -> None:
    committed = json.loads(OPENAPI_V2_PATH.read_text(encoding="utf-8"))
    assert committed == v2_schema(), "Обновите контракт: uv run python -m geostart.api.openapi"
