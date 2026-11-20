import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from geostart.release.compare import as_json, compare, failed, load_thresholds, render
from geostart.release.manifest import build_manifest, write_manifest

MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class RebuildResult:
    version: str
    previous_version: str
    report_dir: Path
    failed: int
    total: int
    kept: bool


def releases_dir(root: Path) -> Path:
    return root / "releases"


def backup(root: Path, target: Path, cities: list[str], niches: list[str]) -> None:
    if target.exists():
        shutil.rmtree(target)
    for city in cities:
        source = root / "processed" / city
        if source.exists():
            shutil.copytree(source, target / "processed" / city)
        for niche in niches:
            score = root / "scores" / f"{city}_{niche}.parquet"
            if score.exists():
                (target / "scores").mkdir(parents=True, exist_ok=True)
                shutil.copy2(score, target / "scores" / score.name)


def restore(root: Path, saved: Path, cities: list[str], niches: list[str]) -> None:
    for city in cities:
        source = saved / "processed" / city
        destination = root / "processed" / city
        if destination.exists():
            shutil.rmtree(destination)
        if source.exists():
            shutil.copytree(source, destination)
        for niche in niches:
            name = f"{city}_{niche}.parquet"
            current = root / "scores" / name
            current.unlink(missing_ok=True)
            if (saved / "scores" / name).exists():
                shutil.copy2(saved / "scores" / name, current)


def rebuild(
    root: Path,
    cities: list[str],
    niches: list[str],
    refresh_city: Callable[[str], object] | None,
    score: Callable[[str, str], object],
    accept: bool = False,
) -> RebuildResult:
    previous = build_manifest(root)
    saved = releases_dir(root) / "previous"
    backup(root, saved, cities, niches)
    try:
        for city in cities:
            if refresh_city is not None:
                refresh_city(city)
            for niche in niches:
                score(city, niche)
    except BaseException:
        restore(root, saved, cities, niches)
        raise
    current = build_manifest(root)
    checks = compare(previous, current, load_thresholds(), saved, root, cities=set(cities))
    problems = failed(checks)
    kept = accept or not problems
    report_dir = releases_dir(root) / current["version"]
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "report.md").write_text(render(previous, current, checks), encoding="utf-8")
    (report_dir / "checks.json").write_text(
        json.dumps(as_json(checks), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_manifest(current, report_dir / MANIFEST_NAME)
    if kept:
        write_manifest(current, root / MANIFEST_NAME)
    else:
        restore(root, saved, cities, niches)
    return RebuildResult(
        version=current["version"],
        previous_version=previous["version"],
        report_dir=report_dir,
        failed=len(problems),
        total=len(checks),
        kept=kept,
    )
