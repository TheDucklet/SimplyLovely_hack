import argparse
import json

import numpy as np
import pandas as pd
import yaml

from geostart import settings
from geostart.config import load_cities, load_niches
from geostart.economics.geoplatform import STUB_LAYER_VERSION, SquareGrid, stub_path
from geostart.model.data import city_directory
from geostart.model.demand import DemandKind, cell_demand, demand_kind, demand_ranges
from geostart.research import city_parameters

LOWER_SHARE = 0.75
UPPER_SHARE = 1.3
NOISE_SIGMA = 0.2
RESIDENT_FOOTFALL = 0.5
WORKER_FOOTFALL = 1.0
STOP_FOOTFALL = 250.0
METRO_FOOTFALL = 3000.0
METRO_RADIUS_M = 300.0
STUB_SEED = 2026


def median_parameters(niche: str, city: str) -> dict[str, float]:
    with (settings.research_dir() / "niche_params" / f"{niche}.yaml").open(encoding="utf-8") as stream:
        parameters = city_parameters(yaml.safe_load(stream), city)
    ranges = demand_ranges(niche, parameters["demand"])
    return {name: float(bounds["p50"]) for name, bounds in ranges.items() if isinstance(bounds, dict)}


def footfall(features: pd.DataFrame) -> np.ndarray:
    metro = (
        features["metro_dist_m"].to_numpy(dtype=float)
        if "metro_dist_m" in features
        else np.full(len(features), np.inf)
    )
    return (
        features["residents"].to_numpy(dtype=float) * RESIDENT_FOOTFALL
        + features["workers"].to_numpy(dtype=float) * WORKER_FOOTFALL
        + np.nan_to_num(features["transit_stops_n"].to_numpy(dtype=float)) * STOP_FOOTFALL
        + np.where(np.nan_to_num(metro, nan=np.inf) <= METRO_RADIUS_M, METRO_FOOTFALL, 0.0)
    )


def build_city(city: str) -> pd.DataFrame:
    features = pd.read_parquet(city_directory(city) / "hex_features.parquet")
    grid = SquareGrid.around(features["lat"].to_numpy(dtype=float), features["lon"].to_numpy(dtype=float))
    rows, columns = grid.indices(features["lat"].to_numpy(dtype=float), features["lon"].to_numpy(dtype=float))
    keys = pd.Series([f"{row}_{column}" for row, column in zip(rows, columns, strict=True)])
    frame = pd.DataFrame({"square_id": keys, "row": rows, "column": columns, "footfall": footfall(features)})
    generator = np.random.default_rng(np.random.SeedSequence([STUB_SEED, sum(map(ord, city))]))
    niches = [niche.code for niche in load_niches() if demand_kind(niche.code) == DemandKind.VISITS]
    for niche in niches:
        frame[niche] = cell_demand(features, niche, median_parameters(niche, city))
    grouped = frame.groupby(["square_id", "row", "column"], as_index=False).sum(numeric_only=True)
    bounds = np.array(
        [grid.bounds(int(row), int(column)) for row, column in zip(grouped.row, grouped.column, strict=True)]
    )
    result = pd.DataFrame(
        {
            "city": city,
            "square_id": grouped.square_id,
            "south": bounds[:, 0],
            "west": bounds[:, 1],
            "north": bounds[:, 2],
            "east": bounds[:, 3],
            "footfall_day_p10": (grouped.footfall * LOWER_SHARE).round(),
            "footfall_day_p50": grouped.footfall.round(),
            "footfall_day_p90": (grouped.footfall * UPPER_SHARE).round(),
        }
    )
    for niche in niches:
        noise = generator.lognormal(0.0, NOISE_SIGMA, len(grouped))
        middle = grouped[niche].to_numpy(dtype=float) * noise
        result[f"spend_{niche}_p10"] = (middle * LOWER_SHARE).round()
        result[f"spend_{niche}_p50"] = middle.round()
        result[f"spend_{niche}_p90"] = (middle * UPPER_SHARE).round()
    result["layer_version"] = STUB_LAYER_VERSION
    return result


def main(argv: list[str] | None = None) -> None:
    codes = [city.code for city in load_cities()]
    parser = argparse.ArgumentParser(description="Синтетические слои заглушки геоплатформы банка")
    parser.add_argument("--city", required=True, choices=[*codes, "all"])
    arguments = parser.parse_args(argv)
    for city in codes if arguments.city == "all" else [arguments.city]:
        layers = build_city(city)
        path = stub_path(city)
        path.parent.mkdir(parents=True, exist_ok=True)
        layers.to_parquet(path, index=False)
        print(json.dumps({"city": city, "squares": len(layers), "path": str(path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
