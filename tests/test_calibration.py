import importlib.util
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
