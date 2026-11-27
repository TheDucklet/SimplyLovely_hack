import pandas as pd

from geostart.closed_coffee import classify_points, summarize


def test_classify_points_separates_working_uncertain_and_closed() -> None:
    historical = pd.DataFrame(
        {
            "global_id": ["same", "near", "gone"],
            "name": ["coffee", "coffee", "coffee"],
            "lat": [55.75, 55.75, 55.76],
            "lon": [37.60, 37.60, 37.61],
        }
    )
    current = pd.DataFrame(
        {
            "global_id": ["same", "new"],
            "name": ["coffee", "coffee"],
            "lat": [55.75, 55.75],
            "lon": [37.60, 37.6005],
        }
    )
    result = classify_points(historical, current)
    assert result.set_index("global_id")["class"].to_dict() == {
        "same": "working",
        "near": "uncertain",
        "gone": "closed",
    }


def test_summarize_reports_coverage_and_risk() -> None:
    points = pd.DataFrame(
        {
            "revenue_p50": [100.0, 200.0, None],
            "risk_level": ["high", "low", None],
            "payback_months_p50": [10.0, 20.0, None],
        }
    )
    summary = summarize(points)
    assert summary["points"] == 3
    assert summary["scored_points"] == 2
    assert summary["coverage"] == 2 / 3
    assert summary["revenue_p50"] == 150.0
    assert summary["high_risk_share"] == 0.5
