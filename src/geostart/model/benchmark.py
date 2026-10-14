import argparse
import logging
from pathlib import Path
from time import perf_counter

import yaml

from geostart import settings
from geostart.model.data import load_demand_inputs
from geostart.model.demand import DEFAULT_RUNS, DEFAULT_SEED, Niche, simulate_demand


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Замер расчёта спроса без записи в каталог данных")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--research-dir", type=Path, default=settings.research_dir())
    parser.add_argument("--city", choices=("moscow", "tula"), default="moscow")
    parser.add_argument("--niche", choices=list(Niche), default=Niche.COFFEE)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    started = perf_counter()
    features, competitors = load_demand_inputs(arguments.city, arguments.data_dir)
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
