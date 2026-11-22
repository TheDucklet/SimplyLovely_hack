import copy
import shutil
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from geostart.model import score_city
from geostart.pipeline.fixtures import write_fixtures
from geostart.release.__main__ import THRESHOLDS_EXCEEDED, main
from geostart.release.compare import compare, failed, load_thresholds, render
from geostart.release.manifest import build_manifest, file_hash
from geostart.release.package import package, verify
from geostart.release.rebuild import rebuild


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(root))
    monkeypatch.setenv("GEOSTART_USE_MOCKS", "false")
    write_fixtures("tula", root / "processed" / "tula")
    score_city("tula", "coffee")
    return root


def scale_revenue(root: Path, factor: float) -> None:
    path = root / "scores" / "tula_coffee.parquet"
    scores = pd.read_parquet(path)
    scores[["revenue_p10", "revenue_p50", "revenue_p90"]] *= factor
    scores.to_parquet(path, index=False)


def test_manifest_describes_city_and_scores(data_root: Path) -> None:
    manifest = build_manifest(data_root)
    city = manifest["cities"]["tula"]
    assert city["cells"] > 0 and city["residents"] > 0
    assert "coffee" in city["competitors"]
    score = manifest["scores"]["tula/coffee"]
    assert score["cells"] == city["cells"]
    assert sum(score["risk_share"].values()) == pytest.approx(1, abs=1e-3)
    assert manifest["files"]["scores/tula_coffee.parquet"] == file_hash(
        data_root / "scores" / "tula_coffee.parquet"
    )
    assert manifest["version"].startswith(manifest["created_at"][:10])


def test_compare_flags_only_changes_above_thresholds(data_root: Path) -> None:
    previous = build_manifest(data_root)
    current = copy.deepcopy(previous)
    current["version"] = "next"
    current["cities"]["tula"]["residents"] = round(previous["cities"]["tula"]["residents"] * 1.05)
    assert failed(compare(previous, current, load_thresholds())) == []
    current["cities"]["tula"]["residents"] = round(previous["cities"]["tula"]["residents"] * 1.3)
    current["scores"]["tula/coffee"]["risk_share"]["high"] += 0.2
    problems = failed(compare(previous, current, load_thresholds()))
    assert {check.metric for check in problems} == {"жителей", "доля риска high"}
    report = render(previous, current, compare(previous, current, load_thresholds()))
    assert "выше порогов 2 проверок" in report
    assert report.index("выше порога |") < report.index("норма |")


def test_compare_reports_new_and_missing_parts(data_root: Path) -> None:
    previous = build_manifest(data_root)
    current = copy.deepcopy(previous)
    current["cities"]["moscow"] = current["cities"]["tula"]
    del current["scores"]["tula/coffee"]
    checks = compare(previous, current, load_thresholds())
    notes = {(check.scope, check.note, check.passed) for check in checks if check.note}
    assert ("moscow", "новый город", True) in notes
    assert ("tula/coffee", "расчёт пропал", False) in notes


def test_rebuild_keeps_stable_version(data_root: Path) -> None:
    refreshed = []
    result = rebuild(data_root, ["tula"], ["coffee"], refreshed.append, score_city)
    assert refreshed == ["tula"]
    assert result.kept and result.failed == 0
    assert (data_root / "manifest.json").exists()
    report = (result.report_dir / "report.md").read_text(encoding="utf-8")
    assert "доля ячеек с сильным изменением выручки" in report


def test_rebuild_restores_data_when_thresholds_exceeded(data_root: Path) -> None:
    before = file_hash(data_root / "scores" / "tula_coffee.parquet")

    def broken_score(city: str, niche: str) -> None:
        scale_revenue(data_root, 3.0)

    result = rebuild(data_root, ["tula"], ["coffee"], None, broken_score)
    assert not result.kept and result.failed > 0
    assert file_hash(data_root / "scores" / "tula_coffee.parquet") == before
    assert not (data_root / "manifest.json").exists()
    accepted = rebuild(data_root, ["tula"], ["coffee"], None, broken_score, accept=True)
    assert accepted.kept
    assert file_hash(data_root / "scores" / "tula_coffee.parquet") != before


def test_rebuild_restores_data_after_pipeline_error(data_root: Path) -> None:
    before = file_hash(data_root / "processed" / "tula" / "hex_features.parquet")

    def failing_refresh(city: str) -> None:
        (data_root / "processed" / "tula" / "hex_features.parquet").write_bytes(b"broken")
        raise RuntimeError("источник недоступен")

    with pytest.raises(RuntimeError):
        rebuild(data_root, ["tula"], ["coffee"], failing_refresh, score_city)
    assert file_hash(data_root / "processed" / "tula" / "hex_features.parquet") == before


def test_package_round_trip_and_verify(data_root: Path, tmp_path: Path) -> None:
    archive = package(data_root, tmp_path / "dist", with_basemap=False)
    checksum = archive.with_name(archive.name + ".sha256").read_text(encoding="utf-8").split()[0]
    assert checksum == file_hash(archive)
    target = tmp_path / "unpacked"
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        bundle.extractall(target)
    assert "data/manifest.json" in names
    assert "data/processed/tula/hex_features.parquet" in names
    assert verify(target / "data") == []
    (target / "data" / "scores" / "tula_coffee.parquet").write_bytes(b"changed")
    assert verify(target / "data") == ["контрольная сумма не совпадает у scores/tula_coffee.parquet"]


def test_cli_compare_returns_code_for_exceeded_thresholds(data_root: Path, tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    shutil.copytree(data_root, previous)
    assert main(["compare", str(previous)]) == 0
    scale_revenue(data_root, 3.0)
    assert main(["compare", str(previous)]) == THRESHOLDS_EXCEEDED
