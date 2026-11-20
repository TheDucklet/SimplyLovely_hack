import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml

from geostart.model import score_city
from geostart.pipeline.fixtures import write_fixtures
from geostart.quality.__main__ import main
from geostart.quality.checks import ERROR, errors, run_checks, warnings
from geostart.quality.passport import PASSPORT_PATH, render_passport
from geostart.release.package import QualityError, package
from geostart.release.rebuild import rebuild
from geostart.settings import config_dir


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(root))
    monkeypatch.setenv("GEOSTART_USE_MOCKS", "false")
    write_fixtures("tula", root / "processed" / "tula")
    score_city("tula", "coffee")
    return root


def edit(path: Path, change) -> None:
    frame = pd.read_parquet(path)
    change(frame)
    frame.to_parquet(path, index=False)


def failed_checks(root: Path) -> set[tuple[str, str]]:
    return {(result.dataset, result.check) for result in errors(run_checks(root, ["tula"]))}


def test_fixture_data_has_no_errors(data_root: Path) -> None:
    results = run_checks(data_root, ["tula"])
    assert errors(results) == []
    assert {result.dataset for result in results} >= {"hex_features", "competitors", "wages", "scores/coffee"}
    assert ("scores/grocery", "расчёт есть") in {
        (result.dataset, result.check) for result in warnings(results)
    }


def test_checks_find_broken_values(data_root: Path) -> None:
    folder = data_root / "processed" / "tula"

    def break_hexes(frame: pd.DataFrame) -> None:
        frame.loc[0, "residents"] = -5
        frame.loc[1, "lat"] = 10.0
        frame.loc[2, "h3"] = frame.loc[3, "h3"]

    def break_competitors(frame: pd.DataFrame) -> None:
        frame.loc[0, "niche"] = "casino"

    def break_wages(frame: pd.DataFrame) -> None:
        frame.loc[0, "salary_p25"] = frame.loc[0, "salary_p50"] + 1
        frame.loc[1, "salary_p50"] = 5_000_000

    def break_scores(frame: pd.DataFrame) -> None:
        frame.loc[0, "revenue_p10"] = frame.loc[0, "revenue_p90"] + 1
        frame.loc[1, "risk_level"] = "unknown"

    edit(folder / "hex_features.parquet", break_hexes)
    edit(folder / "competitors.parquet", break_competitors)
    edit(folder / "wages.parquet", break_wages)
    edit(data_root / "scores" / "tula_coffee.parquet", break_scores)
    assert failed_checks(data_root) >= {
        ("hex_features", "признаки не отрицательные"),
        ("hex_features", "координаты внутри границы города"),
        ("hex_features", "ячейки не повторяются"),
        ("competitors", "ниша из справочника"),
        ("wages", "p25 ≤ p50 ≤ p75"),
        ("wages", "медиана зарплаты от 15 000 до 400 000 ₽"),
        ("scores/coffee", "выручка p10 ≤ p50 ≤ p90"),
        ("scores/coffee", "уровень риска из справочника"),
        ("scores/coffee", "расчёт покрывает все ячейки"),
    }


def test_old_wages_and_missing_professions_are_warnings(data_root: Path) -> None:
    edit(
        data_root / "processed" / "tula" / "wages.parquet",
        lambda frame: frame.drop(frame.index[frame["profession"] == "barista"], inplace=True),
    )
    later = date(2030, 1, 1)
    results = run_checks(data_root, ["tula"], today=later)
    flagged = {(result.check, result.severity) for result in results if not result.passed}
    assert ("есть зарплата каждой профессии ниш", "warning") in flagged
    assert ("зарплаты моложе 180 дней", "warning") in flagged
    assert errors(results) == []


def test_rebuild_rejects_version_with_quality_errors(data_root: Path) -> None:
    def broken_score(city: str, niche: str) -> None:
        score_city(city, niche)
        edit(
            data_root / "scores" / "tula_coffee.parquet",
            lambda frame: frame.__setitem__("risk_level", "unknown"),
        )

    result = rebuild(data_root, ["tula"], ["coffee"], None, broken_score)
    assert result.quality_errors > 0 and not result.kept
    assert "уровень риска из справочника" in (result.report_dir / "quality.md").read_text(encoding="utf-8")
    assert set(pd.read_parquet(data_root / "scores" / "tula_coffee.parquet")["risk_level"]) <= {
        "low",
        "medium",
        "high",
    }


def test_package_contains_quality_report_and_refuses_errors(data_root: Path, tmp_path: Path) -> None:
    archive = package(data_root, tmp_path / "dist", with_basemap=False)
    with zipfile.ZipFile(archive) as bundle:
        report = bundle.read("data/quality.md").decode("utf-8")
    assert report.startswith("# Отчёт о качестве данных")
    assert "ошибок нет" in report
    edit(
        data_root / "processed" / "tula" / "competitors.parquet",
        lambda frame: frame.loc.__setitem__((0, "niche"), "x"),
    )
    with pytest.raises(QualityError):
        package(data_root, tmp_path / "dist", with_basemap=False)
    assert package(data_root, tmp_path / "forced", with_basemap=False, force=True).exists()


def test_cli_check_returns_error_code(data_root: Path) -> None:
    assert main(["check", "--city", "tula"]) == 0
    edit(
        data_root / "processed" / "tula" / "hex_features.parquet",
        lambda frame: frame.loc.__setitem__((0, "workers"), -1),
    )
    assert main(["check", "--city", "tula"]) == 1
    assert all(result.severity == ERROR for result in errors(run_checks(data_root, ["tula"])))


def test_passport_document_is_current() -> None:
    committed = PASSPORT_PATH.read_text(encoding="utf-8")
    assert committed == render_passport(), "Обновите паспорт: uv run python -m geostart.quality passport"


def test_passport_covers_every_city_and_extract() -> None:
    pipeline = yaml.safe_load((config_dir() / "pipeline.yaml").read_text(encoding="utf-8"))
    text = render_passport()
    for extract in pipeline["osm_extracts"].values():
        assert str(extract["date"]) in text
    for city in pipeline["cities"].values():
        scope = city.get("population_scope") or city["population_region"]
        assert scope["source"] in text
    passport = yaml.safe_load((config_dir() / "data_passport.yaml").read_text(encoding="utf-8"))
    required = {
        "code",
        "name",
        "owner",
        "url",
        "license",
        "content",
        "files",
        "version",
        "update",
        "frequency",
    }
    assert all(required <= set(source) for source in passport["sources"])
