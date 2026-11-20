import argparse
import json
import logging

from geostart.config import load_cities


def main(argv: list[str] | None = None) -> None:
    city_codes = [city.code for city in load_cities()]
    parser = argparse.ArgumentParser(prog="geostart.pipeline", description="Конвейер данных ГеоСтарта")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="загрузить источники и собрать data/processed/<город>")
    run_parser.add_argument("--city", required=True, choices=[*city_codes, "all"])
    run_parser.add_argument("--skip-wages", action="store_true", help="оставить собранные ранее зарплаты")
    wages_parser = commands.add_parser("wages", help="обновить только зарплаты по вакансиям Работы России")
    wages_parser.add_argument("--city", required=True, choices=[*city_codes, "all"])
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from geostart.pipeline.run import refresh_wages, run_city

    selected = city_codes if arguments.city == "all" else [arguments.city]
    for city_code in selected:
        if arguments.command == "wages":
            summary = refresh_wages(city_code)
        else:
            summary = run_city(city_code, skip_wages=arguments.skip_wages)
        print(json.dumps({"city": city_code, **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
