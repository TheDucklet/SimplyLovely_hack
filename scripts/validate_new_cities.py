import argparse

import pandas as pd

from geostart.config import load_niches
from geostart.model.data import configure_environment, scores_directory
from geostart.model.demand import (
    DEFAULT_SEED,
    demand_ranges,
    preparation_distance,
    prepare_model,
    sample_parameters,
)
from geostart.model.service import load_inputs
from geostart.model.validation import leave_one_out_potentials, validation_metrics


def validate(city: str, niche: str) -> dict:
    inputs = load_inputs(city, niche)
    scores = pd.read_parquet(scores_directory() / f"{city}_{niche}.parquet")
    effective = demand_ranges(niche, inputs.parameters["demand"])
    samples = sample_parameters(niche, effective)
    model = prepare_model(
        inputs.features,
        inputs.competitors,
        niche,
        preparation_distance(pd.DataFrame([{name: bounds["p90"] for name, bounds in effective.items()}])),
    )
    potentials = leave_one_out_potentials(model, inputs.competitors, samples)
    label = f"{city}_{niche}"
    metrics, _ = validation_metrics(
        inputs.features,
        inputs.competitors,
        niche,
        scores.revenue_p50.to_numpy(),
        potentials,
        DEFAULT_SEED + sum(map(ord, label)),
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка модели на существующих точках городов")
    parser.add_argument("cities", nargs="+")
    parser.add_argument("--niches", nargs="+", default=[niche.code for niche in load_niches()])
    arguments = parser.parse_args()
    configure_environment()
    print(
        "| Город | Ниша | Точек | ROC AUC | AUC без исключения | Доля в верхних 20% | Lift "
        "| Медиана точек, ₽ | Медиана контроля, ₽ |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for city in arguments.cities:
        for niche in arguments.niches:
            m = validate(city, niche)
            print(
                f"| {city} | {niche} | {m['points']} | {m['roc_auc']:.3f} | {m['naive_auc']:.3f} "
                f"| {m['top20_share'] * 100:.1f}% | {m['lift']:.2f} | {m['existing_revenue_p50']:,.0f} "
                f"| {m['random_revenue_p50']:,.0f} |".replace(",", " "),
                flush=True,
            )


if __name__ == "__main__":
    main()
