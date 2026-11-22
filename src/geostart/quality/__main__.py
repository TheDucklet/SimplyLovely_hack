import argparse
import json
import sys
from pathlib import Path

from geostart.config import load_cities
from geostart.quality.checks import as_json, errors, run_checks, warnings
from geostart.quality.passport import PASSPORT_PATH, write_passport
from geostart.quality.report import render_report
from geostart.settings import data_dir


def main(argv: list[str] | None = None) -> int:
    cities = [city.code for city in load_cities()]
    parser = argparse.ArgumentParser(
        prog="geostart.quality", description="Паспорт и качество данных ГеоСтарта"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="проверить полноту и диапазоны данных")
    check.add_argument("--city", choices=[*cities, "all"], default="all")
    check.add_argument("--json", action="store_true", help="вывести результаты в JSON")
    report = commands.add_parser("report", help="записать отчёт о качестве данных")
    report.add_argument("--output", type=Path, help="по умолчанию data/quality.md")
    passport = commands.add_parser("passport", help="собрать docs/data-passport.md")
    passport.add_argument("--output", type=Path, default=PASSPORT_PATH)
    arguments = parser.parse_args(argv)
    root = data_dir()

    if arguments.command == "passport":
        print(f"Паспорт данных записан в {write_passport(arguments.output)}")
        return 0
    selected = None if arguments.command == "report" or arguments.city == "all" else [arguments.city]
    results = run_checks(root, selected)
    if arguments.command == "report":
        output = arguments.output or root / "quality.md"
        output.write_text(render_report(root, results), encoding="utf-8", newline="\n")
        print(f"Отчёт о качестве записан в {output}")
    elif arguments.json:
        print(json.dumps(as_json(results), ensure_ascii=False, indent=2))
    else:
        for result in [*errors(results), *warnings(results)]:
            print(
                f"{result.severity} {result.city} {result.dataset}: {result.check} {result.detail}".rstrip()
            )
    print(f"Проверок {len(results)}, ошибок {len(errors(results))}, предупреждений {len(warnings(results))}")
    return 1 if errors(results) else 0


if __name__ == "__main__":
    sys.exit(main())
