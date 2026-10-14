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
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from geostart.pipeline.run import run_city

    selected = city_codes if arguments.city == "all" else [arguments.city]
    for city_code in selected:
        summary = run_city(city_code)
        print(json.dumps({"city": city_code, **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
