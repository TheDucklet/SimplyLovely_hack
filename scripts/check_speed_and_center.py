import argparse
import cProfile
import json
import logging
import os
import pstats
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from geostart.model import evaluate_location
from geostart.model.data import configure_environment, scores_directory
from geostart.model.demand import prepare_model, sample_parameters
from geostart.model.finance import calculate_finance, risk_levels, sample_finance_parameters
from geostart.model.service import city_context, load_inputs, rent_multipliers, rent_rates
from geostart.model.simulation import simulate_revenues

CITIES = ("moscow", "tula")
NICHES = ("coffee", "pickup_point")
SENSITIVITY_PARAMETERS = (
    "orders_per_resident_month",
    "marketplace_share",
    "max_walk_distance_m",
    "max_pickup_distance_m",
    "outside_option_weight",
)


def occupied_distribution(scores: pd.DataFrame, points: pd.DataFrame, niche: str) -> list[float]:
    return (
        scores.loc[scores.h3.isin(points.loc[points.niche.eq(niche), "h3"]), "revenue_p50"]
        .quantile([0.1, 0.5, 0.9])
        .tolist()
    )


def endpoint_sensitivity(city: str, output: Path) -> list[dict]:
    inputs = load_inputs(city, "pickup_point")
    samples = sample_parameters("pickup_point", inputs.parameters["demand"])
    maximum = max(
        float(inputs.parameters["demand"][name]["p90"])
        for name in ("max_walk_distance_m", "max_pickup_distance_m")
    )
    model = prepare_model(inputs.features, inputs.competitors, "pickup_point", maximum)
    occupied = inputs.features.h3.isin(
        inputs.competitors.loc[inputs.competitors.niche.eq("pickup_point"), "h3"]
    )
    rows = []
    for name in SENSITIVITY_PARAMETERS:
        row = {"city": city, "parameter": name}
        for endpoint in ("p10", "p90"):
            changed = samples.copy()
            value = float(inputs.parameters["demand"][name][endpoint])
            changed[name] = value
            values = np.median(simulate_revenues(model, changed), axis=0)
            row[endpoint] = value
            row[f"revenue_{endpoint}"] = float(np.median(values[occupied]))
        rows.append(row)
        (output / f"{city}_sensitivity.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        logging.info("%s чувствительность %s %.2f / %.2f", city, name, row["revenue_p10"], row["revenue_p90"])
    return rows


def rental_comparison(city: str, niche: str) -> dict:
    context = city_context(city, niche)
    inputs = context.inputs
    revenues = simulate_revenues(context.model, context.samples)
    samples = sample_finance_parameters(inputs.parameters)
    finances = []
    for variant in (replace(inputs, rent_adjustment={}), inputs):
        finances.append(
            calculate_finance(
                revenues,
                samples,
                rent_rates(variant, inputs.features),
                inputs.salary,
                inputs.parameters["tax_regime_default"],
                inputs.taxes,
                niche=niche,
            )
        )
    eligible = rent_multipliers(inputs, inputs.features) < 1
    return {
        "city": city,
        "niche": niche,
        "affected_cells": int(eligible.sum()),
        "before_risk": pd.Series(risk_levels(finances[0].profits)).value_counts().to_dict(),
        "after_risk": pd.Series(risk_levels(finances[1].profits)).value_counts().to_dict(),
        "before_affected_rent_median": float(np.median(finances[0].rent[:, eligible]))
        if eligible.any()
        else None,
        "after_affected_rent_median": float(np.median(finances[1].rent[:, eligible]))
        if eligible.any()
        else None,
    }


def main(argv: list[str] | None = None) -> None:
    configure_environment()
    parser = argparse.ArgumentParser(description="Скорость и проверка модели S1-R5b")
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--skip-sensitivity", action="store_true")
    args = parser.parse_args(argv)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    before = json.loads((args.baseline_dir / "before.json").read_text(encoding="utf-8"))
    results = {"reports": [], "scores": [], "sensitivity": [], "rent": []}
    target = output / "results.json"
    started = perf_counter()
    command = subprocess.run(
        [sys.executable, "-m", "geostart.model", "score", "--city", "all", "--niche", "all"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=True,
    )
    results["score_all_seconds"] = perf_counter() - started
    (output / "score.log").write_text(command.stdout + command.stderr, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.info("Расчёт всех городов %.3f с", results["score_all_seconds"])
    for city in CITIES:
        for niche in NICHES:
            inputs = load_inputs(city, niche)
            scores = pd.read_parquet(scores_directory() / f"{city}_{niche}.parquet")
            previous = pd.read_parquet(args.baseline_dir / f"{city}_{niche}_before.parquet")
            results["scores"].append(
                {
                    "city": city,
                    "niche": niche,
                    "before_distribution": occupied_distribution(previous, inputs.competitors, niche),
                    "after_distribution": occupied_distribution(scores, inputs.competitors, niche),
                    "before_risk": previous.risk_level.value_counts().to_dict(),
                    "after_risk": scores.risk_level.value_counts().to_dict(),
                }
            )
            timings = []
            for item in before["reports"]:
                if item["city"] != city or item["niche"] != niche:
                    continue
                started = perf_counter()
                report = evaluate_location(city, niche, item["lat"], item["lon"])
                last_location = (item["lat"], item["lon"])
                elapsed = perf_counter() - started
                timings.append(elapsed)
                results["reports"].append(
                    {
                        "city": city,
                        "niche": niche,
                        "address": item["address"],
                        "lat": item["lat"],
                        "lon": item["lon"],
                        "seconds": elapsed,
                        "report": report.model_dump(),
                    }
                )
            profile = cProfile.Profile()
            profile.runcall(evaluate_location, city, niche, *last_location)
            profile.dump_stats(output / f"after_{city}_{niche}.prof")
            with (output / f"after_{city}_{niche}_profile.txt").open("w", encoding="utf-8") as stream:
                pstats.Stats(profile, stream=stream).strip_dirs().sort_stats("cumtime").print_stats(30)
            logging.info(
                "%s %s p95 %.3f с, холодный %.3f с", city, niche, np.quantile(timings, 0.95), timings[0]
            )
            target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    addresses = pd.read_parquet(load_inputs("moscow", "coffee").directory / "addresses.parquet")
    address = addresses.loc[addresses.address.eq("Новоясеневский проспект, 1")].iloc[0]
    results["novoyasenevsky"] = evaluate_location(
        "moscow", "coffee", float(address.lat), float(address.lon)
    ).model_dump()
    for city in CITIES:
        if not args.skip_sensitivity:
            results["sensitivity"].extend(endpoint_sensitivity(city, output))
        for niche in NICHES:
            results["rent"].append(rental_comparison(city, niche))
        target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
