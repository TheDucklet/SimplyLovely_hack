import argparse
import hashlib
import json
import logging
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from geostart import settings
from geostart.model import evaluate_location, score_city
from geostart.model.benchmark import benchmark_comparison
from geostart.model.data import city_directory, configure_environment
from geostart.model.demand import (
    DEFAULT_SEED,
    DemandModel,
    demand_ranges,
    niche_defaults,
    preparation_distance,
    prepare_model,
    sample_parameters,
)
from geostart.model.factors import competition_reference
from geostart.model.finance import payback_months, risk_levels
from geostart.model.service import CityInputs, load_inputs, nearby_indices, run_simulation
from geostart.model.validation import (
    leave_one_out_potentials,
    pickup_decomposition,
    sensitivity,
    validation_metrics,
)

CITIES = ("moscow", "tula")
NICHES = ("coffee", "pickup_point")
CASE_COORDINATES = (55.759913, 37.612753)
SCENARIO_PAYOUT_RUB = 100.0


def verify_baseline_inputs(output: Path) -> None:
    paths = [path for city in CITIES for path in city_directory(city).iterdir() if path.is_file()]
    paths.extend(path for path in settings.research_dir().rglob("*") if path.is_file())
    checksums = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    manifest = output / "input_checksums.json"
    if manifest.is_file():
        previous = {
            str(Path(path).resolve()): digest
            for path, digest in json.loads(manifest.read_text(encoding="utf-8")).items()
        }
        if previous != checksums:
            raise ValueError(
                "Исходные данные или исследование изменились, выберите новый каталог результатов"
            )
    elif any((output / "before").glob("*.parquet")):
        raise ValueError("Для сохранённого исходного расчёта нужны контрольные суммы входов")
    else:
        manifest.write_text(json.dumps(checksums, ensure_ascii=False, indent=2), encoding="utf-8")


def score_summary(scores: pd.DataFrame) -> dict:
    return {
        "cells": len(scores),
        "revenue_distribution": scores.revenue_p50.quantile([0.1, 0.5, 0.9]).tolist(),
        "risks": scores.risk_level.value_counts().to_dict(),
    }


def legacy_scores(inputs: CityInputs, model: DemandModel, current: pd.DataFrame) -> pd.DataFrame:
    ranges = {
        "outside_option_weight": niche_defaults("coffee")["outside_option_weight"],
        **inputs.parameters["demand"],
    }
    samples = sample_parameters(model.niche, ranges)
    revenues, finance = run_simulation(inputs, model, samples)
    scores = current.copy(deep=True)
    quantiles = np.quantile(revenues, [0.1, 0.5, 0.9], axis=0)
    for index, name in enumerate(("revenue_p10", "revenue_p50", "revenue_p90")):
        scores[name] = quantiles[index]
    scores["profit_p50"] = np.median(finance.profits, axis=0)
    scores["risk_level"] = risk_levels(finance.profits)
    scores["payback_months_p50"] = payback_months(
        np.median(finance.capex, axis=0), scores.profit_p50.to_numpy()
    )
    return scores


def run_validation(output: Path, include_sensitivity: bool = True) -> list[dict]:
    output.mkdir(parents=True, exist_ok=True)
    verify_baseline_inputs(output)
    results = []
    for city in CITIES:
        for niche in NICHES:
            label = f"{city}_{niche}"
            started = perf_counter()
            scores = score_city(city, niche)
            elapsed = perf_counter() - started
            logging.info("%s рассчитан за %.3f с", label, elapsed)
            inputs = load_inputs(city, niche)
            effective = demand_ranges(niche, inputs.parameters["demand"])
            samples = sample_parameters(niche, effective)
            model = prepare_model(
                inputs.features,
                inputs.competitors,
                niche,
                preparation_distance(
                    pd.DataFrame([{name: bounds["p90"] for name, bounds in effective.items()}])
                ),
            )
            potentials = leave_one_out_potentials(model, inputs.competitors, samples)
            seed = DEFAULT_SEED + sum(map(ord, label))
            metrics, observations = validation_metrics(
                inputs.features, inputs.competitors, niche, scores.revenue_p50.to_numpy(), potentials, seed
            )
            observations.to_csv(output / f"{label}_points.csv", index=False)
            result = {
                "city": city,
                "niche": niche,
                "status": inputs.parameters.get("status"),
                "score_seconds": elapsed,
                **score_summary(scores),
                "validation": metrics,
            }
            previous = output / "before" / f"{label}.parquet"
            if not previous.is_file():
                previous.parent.mkdir(parents=True, exist_ok=True)
                legacy_scores(inputs, model, scores).to_parquet(previous, index=False)
            previous_scores = pd.read_parquet(previous)
            if previous_scores.h3.tolist() != scores.h3.tolist():
                raise ValueError("Ячейки исходного расчёта изменились, выберите новый каталог валидации")
            result["before"] = score_summary(previous_scores)
            logging.info(
                "%s AUC %.4f, lift %.3f, точек %d",
                label,
                metrics["roc_auc"],
                metrics["lift"],
                metrics["points"],
            )
            if include_sensitivity:
                logging.info("%s начинается чувствительность по %d параметрам", label, len(samples.columns))
                changes = sensitivity(model, samples, effective)
                for name, bounds in {
                    **inputs.parameters["costs"],
                    "capex_rub": inputs.parameters["capex_rub"],
                }.items():
                    if isinstance(bounds, dict) and "p10" in bounds and "p90" in bounds:
                        median = float(scores.revenue_p50.median())
                        changes.loc[len(changes)] = {
                            "parameter": name,
                            "input_p10": bounds["p10"],
                            "input_p90": bounds["p90"],
                            "revenue_at_p10": median,
                            "revenue_at_p90": median,
                            "median_cell_effect_rub": 0,
                            "mean_absolute_effect_rub": 0,
                            "city_median_change_pct": 0,
                        }
                changes.to_csv(output / f"{label}_sensitivity.csv", index=False)
                result["sensitivity"] = changes.to_dict("records")
                logging.info("%s чувствительность завершена", label)
            result["industry_reference"] = benchmark_comparison(city, niche, scores)
            if niche == "pickup_point":
                chosen = int(
                    np.argmin(np.abs(previous_scores.revenue_p50 - previous_scores.revenue_p50.median()))
                )
                parameters = {name: float(bounds["p50"]) for name, bounds in effective.items()}
                old = {**parameters, "outside_option_weight": 1.0}
                result["decomposition_before"] = pickup_decomposition(model, old, chosen)
                result["decomposition_after"] = pickup_decomposition(model, parameters, chosen)
                points = inputs.competitors.niche.eq(niche).sum()
                result["total_demand_per_existing_point"] = float(
                    inputs.features.residents.sum()
                    * parameters["orders_per_resident_month"]
                    * parameters["marketplace_share"]
                    * parameters["payout_per_order_rub"]
                    / points
                )
                scenario = samples.copy()
                scenario["marketplace_share"] = 1.0
                scenario["payout_per_order_rub"] = SCENARIO_PAYOUT_RUB
                revenues, finance = run_simulation(inputs, model, scenario)
                result["unapproved_scenario"] = {
                    "marketplace_share": 1.0,
                    "payout_per_order_rub": SCENARIO_PAYOUT_RUB,
                    "revenue_distribution": np.quantile(
                        np.median(revenues, axis=0), [0.1, 0.5, 0.9]
                    ).tolist(),
                    "risks": pd.Series(risk_levels(finance.profits)).value_counts().to_dict(),
                    "note": "Условный сценарий, не подтверждён источником и не записан в scores",
                }
            results.append(result)
            (output / "results.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    report = evaluate_location("moscow", "coffee", *CASE_COORDINATES)
    inputs = load_inputs("moscow", "coffee")
    counts = np.array(
        [len(indices) for indices in nearby_indices(inputs.features, inputs.competitors, "coffee")]
    )
    district = str(inputs.features.loc[inputs.features.h3.eq(report.location.h3), "district"].iloc[0])
    factor = next(item for item in report.factors if item.code == "competitors_500m")
    case = {
        "address": "Камергерский переулок, 3",
        "revenue_p50": report.revenue_month.p50,
        "competitor_effect": factor.effect_rub,
        "district": district,
        "district_cells": int(inputs.features.district.eq(district).sum()),
        "reference_count": competition_reference(inputs.features, counts, district),
        "city_reference_count": float(np.median(counts)),
    }
    (output / "kamergersky_after.json").write_text(
        json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return results


def main(argv: list[str] | None = None) -> None:
    configure_environment()
    parser = argparse.ArgumentParser(description="Валидация ГеоСтарта на существующих точках")
    parser.add_argument("--output-dir", type=Path, default=settings.REPOSITORY_ROOT / ".team/out/r4")
    parser.add_argument("--skip-sensitivity", action="store_true")
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_validation(arguments.output_dir, not arguments.skip_sensitivity)


if __name__ == "__main__":
    main()
