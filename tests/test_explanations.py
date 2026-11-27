import json

from geostart import explanations
from geostart.schemas import (
    Assumption,
    Factor,
    LocationReport,
    MoneyRange,
    MonthlyCosts,
    NearbyCompetitor,
    ReportLocation,
)


def sample_report() -> LocationReport:
    return LocationReport(
        city="tula",
        niche="coffee",
        location=ReportLocation(lat=54.2, lon=37.6, h3="8912", address="Тестовая, 1"),
        revenue_month=MoneyRange(p10=800, p50=1000, p90=1200),
        costs_month=MonthlyCosts(rent=100, payroll=200, cogs=300, taxes=50, other=50, total=700),
        profit_month_p50=300,
        capex_rub_p50=2000,
        payback_months_p50=7,
        risk_level="medium",
        factors=[Factor(code="residents", name="Жители", value=3, unit="чел.", effect_rub=100)],
        competitors=[NearbyCompetitor(name="Кофе", lat=54.2, lon=37.6, distance_m=120)],
        assumptions=[Assumption(name="Площадь", value=40, unit="м²", source=None)],
        data_version="2026-11-20",
    )


def test_disabled_explanation_does_not_call_model(monkeypatch) -> None:
    monkeypatch.delenv("GEOSTART_EXPLANATIONS", raising=False)
    assert explanations.generate_explanation(sample_report()) is None


def test_external_endpoint_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("GEOSTART_EXPLANATIONS", "true")
    monkeypatch.setenv("GEOSTART_EXPLANATION_URL", "https://example.com/api/generate")
    assert explanations.generate_explanation(sample_report()) is None


def test_local_response_is_accepted_without_new_numbers(monkeypatch) -> None:
    monkeypatch.setenv("GEOSTART_EXPLANATIONS", "true")
    monkeypatch.setenv("GEOSTART_EXPLANATION_URL", "http://127.0.0.1:11434/api/generate")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            text = "Риск средний. Главный фактор повышает прогноз. Проверьте допущения."
            return json.dumps({"response": text}).encode()

    monkeypatch.setattr(explanations, "urlopen", lambda *_args, **_kwargs: Response())
    assert explanations.generate_explanation(sample_report()).startswith("Риск средний")


def test_local_response_with_unknown_number_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("GEOSTART_EXPLANATIONS", "true")
    monkeypatch.setenv("GEOSTART_EXPLANATION_URL", "http://localhost:11434/api/generate")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"response": "Прогноз составляет 999999 рублей."}).encode()

    monkeypatch.setattr(explanations, "urlopen", lambda *_args, **_kwargs: Response())
    assert explanations.generate_explanation(sample_report()) is None
