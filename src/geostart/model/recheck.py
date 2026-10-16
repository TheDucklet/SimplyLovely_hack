import argparse
import hashlib
import json
import logging
from math import ceil
from pathlib import Path

import h3
import numpy as np
import pandas as pd

from geostart import settings
from geostart.model import evaluate_location
from geostart.model.data import city_directory, configure_environment, scores_directory
from geostart.model.demand import (
    DEFAULT_SEED,
    SEATS_SCALE,
    DemandModel,
    Niche,
    Source,
    cell_demand,
    competitor_attractiveness,
    prepare_model,
    sample_parameters,
)
from geostart.model.factors import competition_reference
from geostart.model.service import CityInputs, load_inputs, nearby_indices
from geostart.model.validation import (
    TOP_FRACTION,
    leave_one_out_potentials,
    point_simulation,
    roc_auc,
    validation_metrics,
)
from geostart.model.validation_run import CITIES, NICHES, score_summary, verify_baseline_inputs

SEAT_SCALES = (10.0, 20.0, 40.0)
SEAT_SCENARIOS = (0, 6, 50)
LEGACY_COFFEE_COUNT = 1980
COMBINED_COFFEE_COUNT = 3469
MOS_RU_COFFEE_COUNT = 2701
REVENUE_TOLERANCE_RUB = 1e-6
CENTRAL_DISTRICTS = ("Тверской", "Арбат", "Хамовники")
RESIDENTIAL_DISTRICTS = ("Ясенево", "Отрадное", "Выхино-Жулебино")
PREFERRED_STREETS = {"Ясенево": "Новоясеневский", "Отрадное": "Хачатуряна"}


def input_changes_since_baseline(manifest: Path) -> list[str]:
    if not manifest.is_file():
        return []
    checksums = json.loads(manifest.read_text(encoding="utf-8"))
    changed = []
    for name, digest in checksums.items():
        original = Path(name)
        group = original.parent.name
        current = (
            city_directory(group) / original.name
            if group in CITIES
            else settings.research_dir() / group / original.name
        )
        if not current.is_file() or hashlib.sha256(current.read_bytes()).hexdigest() != digest:
            changed.append(f"{group}/{original.name}")
    return changed


def legacy_osm_points(labels: pd.DataFrame) -> pd.DataFrame:
    if labels.poi_id.duplicated().any():
        raise ValueError("В прежней разметке повторяются идентификаторы точек")
    points = labels[["poi_id", "h3"]].copy()
    centers = np.array([h3.cell_to_latlng(cell) for cell in points.h3])
    points["lat"], points["lon"] = centers[:, 0], centers[:, 1]
    points["niche"], points["source"], points["seats"] = Niche.COFFEE, Source.OSM, np.nan
    return points


def competitors_for_scale(competitors: pd.DataFrame, scale: float) -> pd.DataFrame:
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Масштаб мест должен быть положительным и конечным")
    changed = competitors.copy(deep=True)
    changed["seats"] = pd.to_numeric(changed["seats"], errors="coerce").astype(float)
    selected = changed.source.eq(Source.MOS_RU)
    changed.loc[selected, "seats"] *= SEATS_SCALE / scale
    return changed


def binary_label_comparison(
    features: pd.DataFrame,
    old_points: pd.DataFrame,
    new_points: pd.DataFrame,
    old_scores: np.ndarray,
    new_scores: np.ndarray,
    seed: int = DEFAULT_SEED,
) -> list[dict]:
    old_labels = features.h3.isin(old_points.h3).to_numpy()
    new_labels = features.h3.isin(new_points.h3).to_numpy()
    available = np.flatnonzero(~(old_labels | new_labels))
    count = min(int(old_labels.sum()), int(new_labels.sum()), len(available))
    controls = np.random.default_rng(seed).choice(available, size=count, replace=False)
    if count == 0:
        raise ValueError("Для сравнения нужны обе разметки и общие контрольные ячейки")
    top_count = ceil(TOP_FRACTION * len(features))
    result = []
    for model_name, values in (("osm", old_scores), ("combined", new_scores)):
        order = np.lexsort((features.h3.to_numpy(), -values))
        top = np.zeros(len(features), dtype=bool)
        top[order[:top_count]] = True
        for labels_name, labels in (("osm", old_labels), ("combined", new_labels)):
            share = float(top[labels].mean())
            result.append(
                {
                    "model": model_name,
                    "labels": labels_name,
                    "positive_cells": int(labels.sum()),
                    "controls": count,
                    "seed": seed,
                    "roc_auc": roc_auc(values[labels], values[controls]),
                    "top20_share": share,
                    "lift": share / (top_count / len(features)),
                }
            )
    return result


def seat_analysis(inputs: CityInputs, model: DemandModel, samples: pd.DataFrame) -> dict:
    points = inputs.competitors.loc[inputs.competitors.niche.eq(Niche.COFFEE)].reset_index(drop=True)
    actual = point_simulation(model, points, samples, competitor_attractiveness(points))
    total_captured = actual.revenues.sum(axis=1)
    city_demand = np.array(
        [
            cell_demand(inputs.features, "coffee", parameters).sum()
            for parameters in samples.to_dict("records")
        ]
    )
    groups = []
    masks = {str(seats): points.source.eq(Source.MOS_RU) & points.seats.eq(seats) for seats in SEAT_SCENARIOS}
    masks["other_mos_ru"] = points.source.eq(Source.MOS_RU) & ~points.seats.isin(SEAT_SCENARIOS)
    masks["osm"] = points.source.eq(Source.OSM)
    for name, mask in masks.items():
        captured = actual.revenues[:, mask.to_numpy()].sum(axis=1)
        groups.append(
            {
                "group": name,
                "points": int(mask.sum()),
                "city_demand_share": float(np.mean(captured / city_demand)),
                "allocated_demand_share": float(np.mean(captured / total_captured)),
            }
        )
    mos_ru = points.loc[points.source.eq(Source.MOS_RU)].reset_index(drop=True)
    scenarios = []
    for seats in SEAT_SCENARIOS:
        candidate = np.full(len(mos_ru), 1 + seats / SEATS_SCALE)
        simulated = point_simulation(model, mos_ru, samples, candidate)
        shares = np.divide(
            simulated.revenues,
            simulated.reachable_demand,
            out=np.zeros_like(simulated.revenues),
            where=simulated.reachable_demand > 0,
        )
        scenarios.append(
            {
                "seats": seats,
                "attractiveness": float(candidate[0]),
                "capture_share_distribution": np.quantile(
                    np.median(shares, axis=0), [0.1, 0.5, 0.9]
                ).tolist(),
            }
        )
    return {
        "mos_ru_points": len(mos_ru),
        "zero_seats": int(mos_ru.seats.eq(0).sum()),
        "missing_seats": int(mos_ru.seats.isna().sum()),
        "median_seats": float(mos_ru.seats.median()),
        "unique_seats": int(mos_ru.seats.nunique()),
        "max_seats": float(mos_ru.seats.max()),
        "captured_city_share": float(np.mean(total_captured / city_demand)),
        "groups": groups,
        "scenarios": scenarios,
    }


def address_checks(inputs: CityInputs, output: Path) -> list[dict]:
    addresses = pd.read_parquet(inputs.directory / "addresses.parquet")
    addresses = addresses.merge(inputs.features[["h3", "district"]], on="h3", validate="many_to_one")
    counts = np.array(
        [len(indices) for indices in nearby_indices(inputs.features, inputs.competitors, "coffee")]
    )
    results = []
    for region, districts in (("center", CENTRAL_DISTRICTS), ("residential", RESIDENTIAL_DISTRICTS)):
        for district in districts:
            selected = addresses.loc[addresses.district.eq(district)].sort_values("address")
            if selected.empty:
                raise ValueError(f"Нет адресов района {district}, выберите район из данных")
            if district == "Тверской":
                preferred = selected.loc[selected.address.eq("Камергерский переулок, 3")]
                if not preferred.empty:
                    selected = preferred
            if district in PREFERRED_STREETS:
                preferred = selected.loc[selected.address.str.contains(PREFERRED_STREETS[district], na=False)]
                if not preferred.empty:
                    selected = preferred
            address = selected.iloc[0]
            report = evaluate_location("moscow", "coffee", float(address.lat), float(address.lon))
            factor = next(factor for factor in report.factors if factor.code == "competitors_500m")
            if abs(factor.effect_rub) > report.revenue_month.p50 + REVENUE_TOLERANCE_RUB:
                raise ValueError("Эффект конкурентов превысил выручку")
            name = f"address_{len(results) + 1}.json"
            (output / name).write_text(report.model_dump_json(indent=2), encoding="utf-8")
            results.append(
                {
                    "region": region,
                    "address": str(address.address),
                    "h3": str(address.h3),
                    "district": district,
                    "revenue_p50": report.revenue_month.p50,
                    "competitor_effect": factor.effect_rub,
                    "district_cells": int(inputs.features.district.eq(district).sum()),
                    "reference_count": competition_reference(inputs.features, counts, district),
                    "top5": [factor.model_dump() for factor in report.factors[:5]],
                }
            )
    return results


def run_recheck(output: Path, baseline: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    verify_baseline_inputs(output)
    historical = json.loads((baseline / "results.json").read_text(encoding="utf-8"))
    old_labels = pd.read_csv(baseline / "moscow_coffee_points.csv")
    if len(old_labels) != LEGACY_COFFEE_COUNT:
        raise ValueError("Для прежней разметки нужны 1980 точек OSM из S1-R4")
    historical = {(row["city"], row["niche"]): row for row in historical}
    result = {
        "main_before_r4b": "291c5b2",
        "comparisons": [],
        "seat_scales": [],
        "baseline_points_sha256": hashlib.sha256(
            (baseline / "moscow_coffee_points.csv").read_bytes()
        ).hexdigest(),
        "baseline_results_sha256": hashlib.sha256((baseline / "results.json").read_bytes()).hexdigest(),
    }
    result["changed_inputs_since_r4"] = input_changes_since_baseline(baseline / "input_checksums.json")
    for city in CITIES:
        for niche in NICHES:
            inputs = load_inputs(city, niche)
            samples = sample_parameters(niche, inputs.parameters["demand"])
            model = prepare_model(
                inputs.features, inputs.competitors, niche, float(samples.max_walk_distance_m.max())
            )
            scores = pd.read_parquet(scores_directory() / f"{city}_{niche}.parquet")
            if scores.h3.tolist() != inputs.features.h3.tolist():
                raise ValueError("Расчёт не соответствует сетке, выполните score --city all --niche all")
            potentials = leave_one_out_potentials(model, inputs.competitors, samples)
            seed = DEFAULT_SEED + sum(map(ord, f"{city}_{niche}"))
            metrics, observations = validation_metrics(
                inputs.features, inputs.competitors, niche, scores.revenue_p50.to_numpy(), potentials, seed
            )
            observations.to_csv(output / f"{city}_{niche}_points.csv", index=False)
            previous = historical[(city, niche)]
            result["comparisons"].append(
                {
                    "city": city,
                    "niche": niche,
                    "historical_before": previous["validation"],
                    "historical_distribution": previous["revenue_distribution"],
                    "after": metrics,
                    "after_distribution": score_summary(scores),
                    "residents": float(inputs.features.residents.sum()),
                    "research_status": inputs.parameters.get("status"),
                }
            )
            logging.info("%s %s, AUC %.4f, lift %.3f", city, niche, metrics["roc_auc"], metrics["lift"])
            if city == "moscow" and niche == Niche.COFFEE:
                coffee_points = inputs.competitors.loc[inputs.competitors.niche.eq(niche)]
                if (
                    len(coffee_points) != COMBINED_COFFEE_COUNT
                    or coffee_points.source.eq(Source.MOS_RU).sum() != MOS_RU_COFFEE_COUNT
                ):
                    raise ValueError("Нужны 3469 кофеен, из них 2701 mos_ru, обновите данные")
                osm = legacy_osm_points(old_labels)
                old_model = prepare_model(inputs.features, osm, niche, model.max_distance_m)
                old_values = np.median(
                    [old_model.revenue(parameters) for parameters in samples.to_dict("records")], axis=0
                )
                old_potentials = leave_one_out_potentials(old_model, osm, samples)
                old_metrics, _ = validation_metrics(
                    inputs.features, osm, niche, old_values, old_potentials, seed
                )
                result["controlled_osm_before"] = old_metrics
                result["binary_labels"] = binary_label_comparison(
                    inputs.features, osm, coffee_points, old_values, scores.revenue_p50.to_numpy()
                )
                old_cells, new_cells = set(osm.h3), set(coffee_points.h3)
                result["label_overlap"] = {
                    "old_cells": len(old_cells),
                    "new_cells": len(new_cells),
                    "intersection": len(old_cells & new_cells),
                    "old_only": len(old_cells - new_cells),
                    "new_only": len(new_cells - old_cells),
                }
                for scale in SEAT_SCALES:
                    changed = competitors_for_scale(inputs.competitors, scale)
                    alternative = prepare_model(inputs.features, changed, niche, model.max_distance_m)
                    values = np.median(
                        [alternative.revenue(parameters) for parameters in samples.to_dict("records")], axis=0
                    )
                    potential = leave_one_out_potentials(alternative, changed, samples)
                    alternative_metrics, _ = validation_metrics(
                        inputs.features, changed, niche, values, potential, seed
                    )
                    result["seat_scales"].append(
                        {
                            "scale": scale,
                            **alternative_metrics,
                            "city_revenue_median": float(np.median(values)),
                        }
                    )
                    logging.info(
                        "Масштаб мест %.0f, AUC %.4f, lift %.3f",
                        scale,
                        alternative_metrics["roc_auc"],
                        alternative_metrics["lift"],
                    )
                result["seats"] = seat_analysis(inputs, model, samples)
            (output / "results.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    result["addresses"] = address_checks(load_inputs("moscow", "coffee"), output)
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> None:
    configure_environment()
    parser = argparse.ArgumentParser(description="Повторная проверка после подключения data.mos.ru")
    parser.add_argument("--output-dir", type=Path, default=settings.REPOSITORY_ROOT / ".team/out/r4b")
    parser.add_argument("--baseline-dir", type=Path, default=settings.REPOSITORY_ROOT / ".team/out/r4")
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_recheck(arguments.output_dir, arguments.baseline_dir)


if __name__ == "__main__":
    main()
