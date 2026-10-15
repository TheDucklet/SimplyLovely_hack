import argparse
import json
import logging

from geostart.config import load_cities
from geostart.model.data import configure_environment


def main(argv: list[str] | None = None) -> None:
    configure_environment()
    city_codes = [city.code for city in load_cities()]
    parser = argparse.ArgumentParser(prog="geostart.storage", description="Хранилище ГеоСтарта в PostgreSQL")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="применить схему из каталога sql/")
    load_parser = commands.add_parser("load", help="загрузить данные и расчёты города в базу")
    load_parser.add_argument("--city", required=True, choices=[*city_codes, "all"])
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from geostart.storage.load import load_cities_into_database, migrate

    if arguments.command == "migrate":
        print(json.dumps({"applied": migrate()}, ensure_ascii=False))
        return
    selected = city_codes if arguments.city == "all" else [arguments.city]
    print(json.dumps(load_cities_into_database(selected), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
