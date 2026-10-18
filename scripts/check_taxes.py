import argparse
import json
import logging
from pathlib import Path
from time import perf_counter

from validate_research_params import address_reports

from geostart.model import score_city
from geostart.model.data import configure_environment
from geostart.model.service import load_inputs

CITIES = ("moscow", "tula")
NICHES = ("coffee", "pickup_point")


def main(argv: list[str] | None = None) -> None:
    configure_environment()
    parser = argparse.ArgumentParser(description="Сверка расходов и риска S1-R5c")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    results = {"scores": [], "addresses": []}
    target = args.output_dir / "results.json"
    for city in CITIES:
        for niche in NICHES:
            inputs = load_inputs(city, niche)
            started = perf_counter()
            scores = score_city(city, niche)
            elapsed = perf_counter() - started
            scores.to_parquet(args.output_dir / f"{city}_{niche}.parquet", index=False)
            results["scores"].append(
                {
                    "city": city,
                    "niche": niche,
                    "salary": inputs.salary,
                    "seconds": elapsed,
                    "risk": scores.risk_level.value_counts().to_dict(),
                    "revenue_quantiles": scores.revenue_p50.quantile([0.1, 0.5, 0.9]).tolist(),
                    "profit_quantiles": scores.profit_p50.quantile([0.1, 0.5, 0.9]).tolist(),
                }
            )
            target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            logging.info("%s %s, расчёт %.3f с, риск %s", city, niche, elapsed, results["scores"][-1]["risk"])
    results["addresses"] = address_reports(args.output_dir)
    results["total_score_seconds"] = sum(row["seconds"] for row in results["scores"])
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
