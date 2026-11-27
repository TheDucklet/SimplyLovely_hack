import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/calibrate_gir_bo.py"
SPEC = importlib.util.spec_from_file_location("calibrate_gir_bo", SCRIPT)
calibration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(calibration)


def test_calibration_metrics_include_interval_boundaries():
    rows = pd.DataFrame(
        {
            "inn": ["a", "a", "b"],
            "revenue_rub": [100, 200, 400],
            "model_p10": [60, 180, 500],
            "model_p50": [80, 200, 600],
            "model_p90": [100, 250, 650],
        }
    )

    result = calibration.metrics(rows)

    assert result["rows"] == 3
    assert result["organizations"] == 2
    assert result["mape"] == pytest.approx(0.7 / 3)
    assert result["bias"] == pytest.approx(1.0)
    assert result["coverage"] == pytest.approx(2 / 3)
    assert calibration.metrics(rows.iloc[:0])["mape"] is None


def test_score_keeps_boundary_failure_and_reuses_forecast(monkeypatch):
    calls = []

    def evaluate(city, niche, lat, lon):
        calls.append((city, niche, lat, lon))
        if lat == 55.66:
            raise ValueError("Точка вне границ города moscow, выберите место внутри границы")
        return SimpleNamespace(revenue_month=SimpleNamespace(p10=10.0, p50=20.0, p90=30.0))

    monkeypatch.setattr(calibration, "evaluate_location", evaluate)
    rows = pd.DataFrame(
        {
            "city": ["moscow"] * 3,
            "review_status": ["located"] * 3,
            "lat": [55.77, 55.77, 55.66],
            "lon": [37.56, 37.56, 37.42],
            "revenue_rub": [200, 220, 180],
        }
    )

    result = calibration.score(rows)

    assert len(calls) == 2
    assert result.loc[0, calibration.MODEL_COLUMNS].tolist() == [120, 240, 360]
    assert result.loc[1, "model_p50"] == 240
    assert pd.isna(result.loc[2, "model_p50"])
    assert result.loc[2, "forecast_error"].startswith(calibration.OUTSIDE_CITY)


@pytest.mark.parametrize(
    ("input_statuses", "options", "verified_count", "diagnostic_count"),
    [
        (None, [], 0, 2),
        (None, ["--verified-input"], 2, 0),
        (["verified", "located"], [], 1, 1),
    ],
)
def test_cli_counts_verified_and_located_separately(
    tmp_path, monkeypatch, input_statuses, options, verified_count, diagnostic_count
):
    rows = pd.DataFrame(
        {
            "inn": ["7700000001", "7700000002"],
            "name": ["A", "B"],
            "city": ["Москва", "Тула"],
            "address": ["A", "B"],
            "year": [2024, 2025],
            "lat": [55.77, 54.20],
            "lon": [37.56, 37.62],
            "revenue_rub": [200, 360],
            "cogs_rub": [60, 100],
            "selling_expenses_rub": [20, 30],
            "report_url": ["https://example.com/report-a", "https://example.com/report-b"],
            "address_url": ["https://example.com/address-a", "https://example.com/address-b"],
        }
    )
    if input_statuses is not None:
        rows["review_status"] = input_statuses
    sample = tmp_path / "sample.csv"
    rows.to_csv(sample, index=False)
    monkeypatch.setattr(
        calibration,
        "evaluate_location",
        lambda *_args: SimpleNamespace(revenue_month=SimpleNamespace(p10=10.0, p50=20.0, p90=30.0)),
    )
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--input", str(sample), "--output-dir", str(tmp_path), *options]
    )

    calibration.main()

    result = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert result["verified"][0]["rows"] == verified_count
    assert result["located_diagnostic"][0]["rows"] == diagnostic_count
    if verified_count == 2:
        assert result["verified"][0]["coverage"] == 1.0
        change = result["trial_adjustment"]["leave_one_organization_out"]
        assert change["mape"] == pytest.approx((0.8 + 4 / 9) / 2)
        assert change["coverage"] == 0.5
