import argparse
import logging
import os
from pathlib import Path
from time import perf_counter

from geostart.config import load_cities, load_niches
from geostart.model.data import configure_environment
from geostart.model.service import score_city


def main(argv: list[str] | None = None) -> None:
    configure_environment()
    cities = [city.code for city in load_cities()]
    niches = [niche.code for niche in load_niches()]
    parser = argparse.ArgumentParser(description="Расчёт ГеоСтарта по реальным данным")
    commands = parser.add_subparsers(dest="command", required=True)
    score = commands.add_parser("score", help="Рассчитать ячейки и сохранить Parquet")
    score.add_argument("--city", choices=[*cities, "all"], required=True)
    score.add_argument("--niche", choices=[*niches, "all"], required=True)
    score.add_argument("--data-dir", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.data_dir is not None:
        os.environ["GEOSTART_DATA_DIR"] = str(arguments.data_dir.resolve())
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for city in cities if arguments.city == "all" else [arguments.city]:
        for niche in niches if arguments.niche == "all" else [arguments.niche]:
            started = perf_counter()
            scores = score_city(city, niche)
            distribution = scores.revenue_p50.quantile([0.1, 0.5, 0.9]).round(2).tolist()
            risk = scores.risk_level.value_counts().to_dict()
            logging.info(
                "Город %s, ниша %s, ячеек %d, время %.3f с, распределение выручки %s, риск %s",
                city,
                niche,
                len(scores),
                perf_counter() - started,
                distribution,
                risk,
            )


if __name__ == "__main__":
    main()
