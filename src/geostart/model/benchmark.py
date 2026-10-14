import argparse
import logging
from pathlib import Path
from time import perf_counter

import pandas as pd
import yaml

from geostart.model.demand import DEFAULT_RUNS, DEFAULT_SEED, Niche, simulate_demand

DATA_FILES = (
    "hex_features.parquet",
    "competitors.parquet",
    "wages.parquet",
    "addresses.parquet",
    "boundary.geojson",
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Замер расчёта спроса без записи в каталог данных")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--research-dir", type=Path, default=Path("research"))
    parser.add_argument("--city", choices=("moscow", "tula"), default="moscow")
    parser.add_argument("--niche", choices=list(Niche), default=Niche.COFFEE)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    arguments = parser.parse_args(argv)
    directory = arguments.data_dir / "processed" / arguments.city
    for name in DATA_FILES:
        if not (directory / name).is_file():
            raise FileNotFoundError(f"Нет файла {directory / name}, распакуйте архив данных")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    started = perf_counter()
    features = pd.read_parquet(directory / "hex_features.parquet")
    competitors = pd.read_parquet(directory / "competitors.parquet")
    with (arguments.research_dir / "niche_params" / f"{arguments.niche}.yaml").open(
        encoding="utf-8"
    ) as stream:
        parameters = yaml.safe_load(stream)
    result = simulate_demand(
        features,
        competitors,
        arguments.niche,
        parameters["demand"],
        arguments.runs,
        arguments.seed,
    )
    elapsed = perf_counter() - started
    logging.info(
        "Город %s, ниша %s, ячеек %d, жителей %.1f, прогонов %d, seed %d, время %.3f с",
        arguments.city,
        arguments.niche,
        len(result),
        features["residents"].sum(),
        arguments.runs,
        arguments.seed,
        elapsed,
    )


if __name__ == "__main__":
    main()
