import json
import shutil
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import pytest
import yaml
from shapely.geometry import box, mapping

from geostart import settings
from geostart.model import evaluate_location, score_city
from geostart.model.__main__ import main
from geostart.pipeline.fixtures import write_fixtures
from geostart.schemas import LocationReport

SCORE_COLUMNS = [
    "h3",
    "revenue_p10",
    "revenue_p50",
    "revenue_p90",
    "profit_p50",
    "payback_months_p50",
    "risk_level",
    "competitors_500m",
]


@pytest.fixture
def model_data(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "research"
    shutil.copytree(settings.research_dir(), root)
    monkeypatch.setattr(settings, "research_dir", lambda: root)
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(tmp_path))
    for city, center in (("moscow", (55.7558, 37.6176)), ("tula", (54.1931, 37.6173))):
        directory = tmp_path / "processed" / city
        write_fixtures(city, directory)
        features = pd.read_parquet(directory / "hex_features.parquet")
        cell = h3.latlng_to_cell(*center, 9)
        features = features.loc[features.h3.isin(h3.grid_disk(cell, 2))].copy()
        features.to_parquet(directory / "hex_features.parquet", index=False)
        competitors = pd.read_parquet(directory / "competitors.parquet").iloc[:0]
        competitors.to_parquet(directory / "competitors.parquet", index=False)
        boundary = mapping(box(center[1] - 0.05, center[0] - 0.05, center[1] + 0.05, center[0] + 0.05))
        (directory / "boundary.geojson").write_text(json.dumps(boundary), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("city", ["moscow", "tula"])
@pytest.mark.parametrize("niche", ["coffee", "pickup_point"])
def test_score_file_and_location_report_agree(model_data: Path, city: str, niche: str) -> None:
    scores = score_city(city, niche)
    written = pd.read_parquet(model_data / "scores" / f"{city}_{niche}.parquet")
    pd.testing.assert_frame_equal(scores, written)
    assert list(scores.columns) == SCORE_COLUMNS
    assert scores.revenue_p10.le(scores.revenue_p50).all()
    assert scores.revenue_p50.le(scores.revenue_p90).all()
    assert scores.payback_months_p50.loc[scores.profit_p50.le(0)].isna().all()
    assert set(scores.risk_level) <= {"low", "medium", "high"}
    cell = scores.iloc[0].h3
    lat, lon = h3.cell_to_latlng(cell)
    report = evaluate_location(city, niche, lat, lon)
    assert isinstance(report, LocationReport)
    assert report.revenue_month.p50 == pytest.approx(scores.iloc[0].revenue_p50)
    assert report.profit_month_p50 == pytest.approx(scores.iloc[0].profit_p50)
    assert report.risk_level == scores.iloc[0].risk_level
    assert report.costs_month.total == pytest.approx(
        sum(getattr(report.costs_month, name) for name in ("rent", "payroll", "cogs", "taxes", "other"))
    )
    effects = [abs(factor.effect_rub) for factor in report.factors]
    assert effects == sorted(effects, reverse=True)
    if city == "tula":
        assert "metro_dist_m" not in [factor.code for factor in report.factors]
    LocationReport.model_validate_json(report.model_dump_json())


def test_user_overrides_and_proxy_wage_are_reported(model_data: Path) -> None:
    directory = model_data / "processed" / "tula"
    wages = pd.read_parquet(directory / "wages.parquet")
    wages["basis"] = "proxy"
    wages.to_parquet(directory / "wages.parquet", index=False)
    features = pd.read_parquet(directory / "hex_features.parquet")
    features["district"] = "Район без ставки"
    features.to_parquet(directory / "hex_features.parquet", index=False)
    lat, lon = h3.cell_to_latlng(features.iloc[0].h3)
    fallback = evaluate_location("tula", "coffee", lat, lon)
    assert any("по медиане" in assumption.name for assumption in fallback.assumptions)
    report = evaluate_location("tula", "coffee", lat, lon, area_m2=40, rent_rub_m2_month=1000)
    assert report.costs_month.rent == 40_000
    assert any("по соседней профессии" in assumption.name for assumption in report.assumptions)
    assert not any("по медиане" in assumption.name for assumption in report.assumptions)


def test_outside_boundary_is_rejected(model_data: Path) -> None:
    with pytest.raises(ValueError, match="вне границ"):
        evaluate_location("moscow", "coffee", 0, 0)


def test_missing_cell_inside_boundary_has_valid_report(model_data: Path) -> None:
    cell = h3.latlng_to_cell(54.1931, 37.6173, 9)
    path = model_data / "processed" / "tula" / "hex_features.parquet"
    features = pd.read_parquet(path)
    features.loc[features.h3.ne(cell)].to_parquet(path, index=False)
    report = evaluate_location("tula", "coffee", *h3.cell_to_latlng(cell))
    assert np.isfinite(report.revenue_month.p50)
    assert any("без признаков" in assumption.name for assumption in report.assumptions)


def test_cli_scores_all_four_combinations(model_data: Path) -> None:
    main(["score", "--city", "all", "--niche", "all"])
    assert {path.name for path in (model_data / "scores").glob("*.parquet")} == {
        f"{city}_{niche}.parquet" for city in ("moscow", "tula") for niche in ("coffee", "pickup_point")
    }


def test_resident_factor_is_exact_cell_counterfactual(model_data: Path) -> None:
    path = model_data / "processed" / "tula" / "hex_features.parquet"
    features = pd.read_parquet(path)
    cell = features.iloc[0].h3
    median = float(features.residents.median())
    lat, lon = h3.cell_to_latlng(cell)
    report = evaluate_location("tula", "coffee", lat, lon)
    factor = next(factor for factor in report.factors if factor.code == "residents")
    features.loc[features.h3.eq(cell), "residents"] = median
    features.to_parquet(path, index=False)
    counterfactual = evaluate_location("tula", "coffee", lat, lon)
    assert factor.effect_rub == pytest.approx(report.revenue_month.p50 - counterfactual.revenue_month.p50)


def test_vat_threshold_warning_is_present(model_data: Path) -> None:
    root = settings.research_dir()
    path = root / "taxes" / "2026.yaml"
    taxes = yaml.safe_load(path.read_text(encoding="utf-8"))
    taxes["vat_threshold_usn_rub_year"]["value"] = 1
    path.write_text(yaml.safe_dump(taxes), encoding="utf-8")
    report = evaluate_location("tula", "coffee", 54.1931, 37.6173)
    assert any(assumption.name == "Предупреждение о НДС" for assumption in report.assumptions)


def test_more_residents_increase_revenue(model_data: Path) -> None:
    path = model_data / "processed" / "tula" / "hex_features.parquet"
    features = pd.read_parquet(path)
    cell = h3.latlng_to_cell(54.1931, 37.6173, 9)
    features.loc[features.h3.eq(cell), ["residents", "workers"]] = 0
    features.to_parquet(path, index=False)
    empty = evaluate_location("tula", "coffee", *h3.cell_to_latlng(cell))
    features.loc[features.h3.eq(cell), "residents"] = 10_000
    features.to_parquet(path, index=False)
    populated = evaluate_location("tula", "coffee", *h3.cell_to_latlng(cell))
    assert populated.revenue_month.p50 > empty.revenue_month.p50


def test_competition_factor_matches_removing_colocated_point(model_data: Path) -> None:
    directory = model_data / "processed" / "tula"
    features = pd.read_parquet(directory / "hex_features.parquet")
    cell = features.iloc[0].h3
    lat, lon = h3.cell_to_latlng(cell)
    empty = pd.read_parquet(directory / "competitors.parquet")
    competitor = pd.DataFrame(
        [
            {
                "poi_id": "test-coffee",
                "niche": "coffee",
                "name": "Тестовая кофейня",
                "brand": None,
                "lat": lat,
                "lon": lon,
                "h3": cell,
                "source": "osm",
                "seats": None,
            }
        ]
    )
    competitor.to_parquet(directory / "competitors.parquet", index=False)
    crowded = evaluate_location("tula", "coffee", lat, lon)
    assert len(crowded.competitors) == 1
    factor = next(item for item in crowded.factors if item.code == "competitors_500m")
    empty.to_parquet(directory / "competitors.parquet", index=False)
    alone = evaluate_location("tula", "coffee", lat, lon)
    assert crowded.revenue_month.p50 < alone.revenue_month.p50
    assert factor.effect_rub == pytest.approx(crowded.revenue_month.p50 - alone.revenue_month.p50)
