import argparse
import hashlib
import json
import logging
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from geostart.model import evaluate_location, score_city
from geostart.model.benchmark import benchmark_comparison
from geostart.model.data import configure_environment
from geostart.model.demand import (
    DEFAULT_SEED,
    OPTIONAL_PARAMETERS,
    DemandModel,
    cell_demand,
    preparation_distance,
    prepare_model,
    sample_parameters,
)
from geostart.model.service import CityInputs, load_inputs
from geostart.model.validation import leave_one_out_potentials, validation_metrics

CITIES = ("moscow", "tula")
NICHES = ("coffee", "pickup_point")
QUANTILE_NAMES = ("p10", "p50", "p90")
FAR_METRO_DISTANCE_M = 1500


def outcome_summary(scores: pd.DataFrame) -> dict:
    finite = scores.payback_months_p50.dropna()
    return {
        "risks": scores.risk_level.value_counts().to_dict(),
        "payback_months": (
            dict(zip(QUANTILE_NAMES, finite.quantile([0.1, 0.5, 0.9]).tolist(), strict=True))
            if len(finite)
            else None
        ),
        "non_payback_share": float(scores.payback_months_p50.isna().mean()),
    }


def validation_result(
    inputs: CityInputs, niche: str, scores: pd.DataFrame, after: bool
) -> tuple[dict, tuple[DemandModel, pd.DataFrame]]:
    ranges = inputs.parameters["demand"].copy()
    if not after:
        for name in OPTIONAL_PARAMETERS[niche]:
            ranges.pop(name, None)
    samples = sample_parameters(niche, ranges)
    upper = pd.DataFrame([{name: bounds["p90"] for name, bounds in ranges.items()}])
    model = prepare_model(inputs.features, inputs.competitors, niche, preparation_distance(upper))
    potentials = leave_one_out_potentials(model, inputs.competitors, samples)
    city = str(inputs.parameters.get("city", inputs.directory.name))
    seed = DEFAULT_SEED + sum(map(ord, f"{city}_{niche}"))
    metrics, observations = validation_metrics(
        inputs.features, inputs.competitors, niche, scores.revenue_p50.to_numpy(), potentials, seed
    )
    return {"validation": metrics, "outcomes": outcome_summary(scores)}, (model, observations)


def pickup_coverage(inputs: CityInputs, model: DemandModel) -> dict:
    parameters = {name: float(bounds["p50"]) for name, bounds in inputs.parameters["demand"].items()}
    residents = inputs.features.residents.to_numpy()
    total = residents.sum()
    radii = (250, parameters["max_walk_distance_m"], 800, parameters["max_pickup_distance_m"])
    result = {
        "uncovered_population": {
            str(int(radius)): float(residents[model.nearest_distances > radius].sum() / total)
            for radius in radii
        }
    }
    demand = cell_demand(inputs.features, "pickup_point", parameters)
    for label, extended in (("before", 0), ("after", parameters["max_pickup_distance_m"])):
        changed = {**parameters, "max_pickup_distance_m": extended}
        weights = model.competition_weights(changed)
        pressure = np.bincount(
            model.origin_indices,
            weights=weights * model.attraction[model.destination_indices],
            minlength=len(residents),
        )
        outside = parameters["outside_option_weight"] / (pressure + parameters["outside_option_weight"])
        result[f"outside_demand_share_{label}_at_p50"] = float(np.sum(demand * outside) / demand.sum())
    return result


def address_reports(output: Path) -> list[dict]:
    reports = []
    for city in CITIES:
        inputs = load_inputs(city, "coffee")
        addresses = pd.read_parquet(inputs.directory / "addresses.parquet")
        addresses = addresses.merge(inputs.features[["h3", "metro_dist_m"]], on="h3")
        if city == "moscow":
            near = addresses.loc[addresses.address.eq("Тверская улица, 10")].iloc[0]
            far = (
                addresses.loc[addresses.metro_dist_m.ge(FAR_METRO_DISTANCE_M)].sort_values("address").iloc[0]
            )
            pickup = addresses.loc[addresses.address.eq("Новоясеневский проспект, 1")].iloc[0]
            selected = (("coffee", near), ("coffee", far), ("pickup_point", pickup))
        else:
            cells = inputs.competitors.loc[inputs.competitors.niche.eq("coffee"), "h3"]
            coffee = addresses.loc[addresses.h3.isin(cells)].sort_values("address").iloc[0]
            cells = inputs.competitors.loc[inputs.competitors.niche.eq("pickup_point"), "h3"]
            pickup = addresses.loc[addresses.h3.isin(cells)].sort_values("address").iloc[0]
            selected = (("coffee", coffee), ("pickup_point", pickup))
        for niche, address in selected:
            started = perf_counter()
            report = evaluate_location(city, niche, float(address.lat), float(address.lon))
            assert abs(report.profit_month_p50 - (report.revenue_month.p50 - report.costs_month.total)) < 1e-6
            name = f"address_{len(reports) + 1}.json"
            (output / name).write_text(report.model_dump_json(indent=2), encoding="utf-8")
            reports.append(
                {
                    "city": city,
                    "niche": niche,
                    "address": str(address.address),
                    "h3": str(address.h3),
                    "metro_dist_m": None if pd.isna(address.metro_dist_m) else float(address.metro_dist_m),
                    "revenue_p50": report.revenue_month.p50,
                    "costs_total": report.costs_month.total,
                    "profit": report.profit_month_p50,
                    "payback": report.payback_months_p50,
                    "risk": report.risk_level,
                    "seconds": perf_counter() - started,
                    "top5": [factor.model_dump() for factor in report.factors[:5]],
                }
            )
            logging.info("Адрес %s рассчитан", address.address)
    return reports


def main(argv: list[str] | None = None) -> None:
    configure_environment()
    parser = argparse.ArgumentParser(description="Проверка параметров исследования S1-R5")
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    results = {"comparisons": [], "coverage": {}, "baseline_checksums": {}}
    output = arguments.output_dir / "results.json"
    for city in CITIES:
        for niche in NICHES:
            path = arguments.baseline_dir / f"{city}_{niche}.parquet"
            results["baseline_checksums"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            before = pd.read_parquet(path)
            inputs = load_inputs(city, niche)
            previous, (_, observations) = validation_result(inputs, niche, before, False)
            previous["benchmark"] = benchmark_comparison(city, niche, before)
            observations.to_csv(arguments.output_dir / f"{city}_{niche}_before_points.csv", index=False)
            logging.info("%s %s, исходная AUC %.4f", city, niche, previous["validation"]["roc_auc"])
            started = perf_counter()
            after = score_city(city, niche)
            elapsed = perf_counter() - started
            current, (model, observations) = validation_result(inputs, niche, after, True)
            current["benchmark"] = benchmark_comparison(city, niche, after)
            observations.to_csv(arguments.output_dir / f"{city}_{niche}_after_points.csv", index=False)
            results["comparisons"].append(
                {"city": city, "niche": niche, "score_seconds": elapsed, "before": previous, "after": current}
            )
            if niche == "pickup_point":
                results["coverage"][city] = pickup_coverage(inputs, model)
            output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            logging.info(
                "%s %s, расчёт %.3f с, AUC %.4f, медиана %.2f",
                city,
                niche,
                elapsed,
                current["validation"]["roc_auc"],
                current["benchmark"]["model"]["p50"],
            )
    results["addresses"] = address_reports(arguments.output_dir)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
