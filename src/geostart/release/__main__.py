import argparse
import json
import logging
import sys
from pathlib import Path

from geostart.config import load_cities, load_niches
from geostart.release.compare import as_json, compare, failed, load_thresholds, render
from geostart.release.manifest import build_manifest, read_manifest, write_manifest
from geostart.release.package import package, verify
from geostart.release.rebuild import MANIFEST_NAME, rebuild
from geostart.settings import data_dir

THRESHOLDS_EXCEEDED = 2


def selected(value: str, codes: list[str]) -> list[str]:
    return codes if value == "all" else [value]


def manifest_of(path: Path) -> dict:
    return read_manifest(path) if path.is_file() else build_manifest(path)


def main(argv: list[str] | None = None) -> int:
    cities = [city.code for city in load_cities()]
    niches = [niche.code for niche in load_niches()]
    parser = argparse.ArgumentParser(
        prog="geostart.release", description="Пересчёт и выпуск данных ГеоСтарта"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    rebuild_parser = commands.add_parser(
        "rebuild", help="пересчитать город и нишу и сравнить с прошлой версией"
    )
    rebuild_parser.add_argument("--city", required=True, choices=[*cities, "all"])
    rebuild_parser.add_argument("--niche", default="all", choices=[*niches, "all"])
    rebuild_parser.add_argument(
        "--skip-pipeline", action="store_true", help="только расчёт модели по готовым данным"
    )
    rebuild_parser.add_argument("--skip-wages", action="store_true", help="оставить собранные ранее зарплаты")
    rebuild_parser.add_argument(
        "--accept", action="store_true", help="оставить новую версию при расхождениях"
    )
    compare_parser = commands.add_parser("compare", help="сравнить две версии данных")
    compare_parser.add_argument("previous", type=Path, help="manifest.json или каталог data прошлой версии")
    compare_parser.add_argument("current", type=Path, nargs="?", help="по умолчанию текущий каталог данных")
    compare_parser.add_argument("--json", action="store_true", help="вывести проверки в JSON")
    commands.add_parser("manifest", help="записать data/manifest.json по текущим файлам")
    package_parser = commands.add_parser("package", help="собрать архив данных для стенда")
    package_parser.add_argument("--output", type=Path, default=Path("dist"))
    package_parser.add_argument("--with-basemap", action="store_true", help="добавить подложку PMTiles")
    commands.add_parser("verify", help="сверить файлы данных с data/manifest.json")
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    root = data_dir()

    if arguments.command == "rebuild":
        from geostart.model.data import configure_environment
        from geostart.model.service import score_city
        from geostart.pipeline.run import run_city

        configure_environment()
        refresh = (
            None if arguments.skip_pipeline else lambda city: run_city(city, skip_wages=arguments.skip_wages)
        )
        result = rebuild(
            root,
            selected(arguments.city, cities),
            selected(arguments.niche, niches),
            refresh,
            score_city,
            accept=arguments.accept,
        )
        print(f"Версия {result.version}, прошлая {result.previous_version}")
        print(
            f"Проверок {result.total}, выше порогов {result.failed}, отчёт {result.report_dir / 'report.md'}"
        )
        if not result.kept:
            print(
                "Расхождения выше порогов, прежние данные возвращены. Чтобы принять версию, добавьте --accept"
            )
            return THRESHOLDS_EXCEEDED
        return 0
    if arguments.command == "compare":
        previous = manifest_of(arguments.previous)
        current_path = arguments.current or root
        current = manifest_of(current_path)
        previous_root = arguments.previous if arguments.previous.is_dir() else None
        current_root = current_path if current_path.is_dir() else None
        checks = compare(previous, current, load_thresholds(), previous_root, current_root)
        if arguments.json:
            print(json.dumps(as_json(checks), ensure_ascii=False, indent=2))
        else:
            sys.stdout.write(render(previous, current, checks))
        return THRESHOLDS_EXCEEDED if failed(checks) else 0
    if arguments.command == "manifest":
        manifest = build_manifest(root)
        write_manifest(manifest, root / MANIFEST_NAME)
        print(f"{root / MANIFEST_NAME}: версия {manifest['version']}, файлов {len(manifest['files'])}")
        return 0
    if arguments.command == "package":
        archive = package(root, arguments.output, arguments.with_basemap)
        print(f"{archive}: {archive.stat().st_size / 1e6:.1f} МБ")
        return 0
    problems = verify(root)
    for problem in problems:
        print(problem)
    print("Файлы данных совпадают с манифестом" if not problems else f"Расхождений {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
