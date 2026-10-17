import argparse
import logging
from pathlib import Path
from time import perf_counter

import pandas as pd
import yaml

from geostart import settings
from geostart.model.data import load_demand_inputs, scores_directory
from geostart.model.demand import DEFAULT_RUNS, DEFAULT_SEED, Niche, simulate_demand
from geostart.model.service import load_inputs
from geostart.research import city_parameters


def benchmark_comparison(city: str, niche: str, scores: pd.DataFrame | None = None) -> dict:
    inputs = load_inputs(city, niche)
    if scores is None:
        path = scores_directory() / f"{city}_{niche}.parquet"
        if not path.is_file():
            raise FileNotFoundError("Нет расчёта города, выполните команду model score")
        scores = pd.read_parquet(path)
    occupied = inputs.competitors.loc[inputs.competitors.niche.eq(niche), "h3"].unique()
    values = scores.loc[scores.h3.isin(occupied), "revenue_p50"]
    if values.empty:
        raise ValueError("Нет рассчитанных ячеек с действующими точками, проверьте данные")
    reference = inputs.parameters.get("benchmarks", {}).get("revenue_rub_month")
    if reference is None:
        raise ValueError("Нет ориентира выручки города, добавьте benchmarks.revenue_rub_month")
    return {
        "city": city,
        "niche": niche,
        "occupied_cells": len(values),
        "model": dict(zip(("p10", "p50", "p90"), values.quantile([0.1, 0.5, 0.9]).tolist(), strict=True)),
        "benchmark": reference,
    }


def print_benchmarks(cities: list[str], niches: list[str]) -> None:
    print("| Город | Ниша | Занятых ячеек | Модель p10 | p50 | p90 | Ориентир p10 | p50 | p90 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for city in cities:
        for niche in niches:
            row = benchmark_comparison(city, niche)
            values = [row[group][key] for group in ("model", "benchmark") for key in ("p10", "p50", "p90")]
            formatted = " | ".join(f"{value:.2f}" for value in values)
            print(f"| {city} | {niche} | {row['occupied_cells']} | {formatted} |")


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
        parameters = city_parameters(yaml.safe_load(stream), arguments.city)
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
