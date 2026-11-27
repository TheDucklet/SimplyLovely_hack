import argparse
import json
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yaml

from geostart.model import evaluate_location
from geostart.research import city_parameters
from geostart.settings import research_dir

matplotlib.use("Agg")

MONTHS_PER_YEAR = 12
QUANTILES = ("p10", "p50", "p90")
MODEL_COLUMNS = [f"model_{level}" for level in QUANTILES]
OUTSIDE_CITY = "Точка вне границ города "
CITIES = {"москва": "moscow", "тула": "tula", "moscow": "moscow", "tula": "tula"}
REQUIRED_COLUMNS = {
    "inn",
    "name",
    "city",
    "address",
    "lat",
    "lon",
    "year",
    "revenue_rub",
    "cogs_rub",
    "selling_expenses_rub",
    "report_url",
    "address_url",
}


class ReviewStatus(StrEnum):
    VERIFIED = "verified"
    LOCATED = "located"
    UNVERIFIED = "unverified"
    EXCLUDED_CITY = "excluded_city"
    EXCLUDED_FORMAT = "excluded_format"
    EXCLUDED_MULTISITE = "excluded_multisite"


LOCATED = {ReviewStatus.VERIFIED, ReviewStatus.LOCATED}


def load_sample(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"inn": "string"})
    missing = REQUIRED_COLUMNS - set(frame)
    if missing:
        raise ValueError(f"В выборке отсутствуют поля {', '.join(sorted(missing))}")
    frame["city"] = frame.city.str.strip().str.casefold().map(CITIES)
    if frame.city.isna().any() or frame.duplicated(["inn", "year"]).any():
        raise ValueError("Проверьте названия городов и повторы ИНН за один год")
    if not np.isfinite(frame.revenue_rub).all() or frame.revenue_rub.le(0).any():
        raise ValueError("Годовая выручка должна быть конечной и положительной")
    has_coordinates = frame[["lat", "lon"]].notna().all(axis=1)
    if frame[["lat", "lon"]].notna().any(axis=1).ne(has_coordinates).any():
        raise ValueError("Для каждой точки нужны обе координаты")
    if "review_status" not in frame:
        frame["review_status"] = np.where(has_coordinates, ReviewStatus.LOCATED, ReviewStatus.UNVERIFIED)
    selected = frame.review_status.isin(LOCATED)
    if (
        not frame.review_status.isin(list(ReviewStatus)).all()
        or selected.ne(has_coordinates).any()
        or not frame.loc[selected, "lat"].between(-90, 90).all()
        or not frame.loc[selected, "lon"].between(-180, 180).all()
    ):
        raise ValueError("Проверьте координаты и отметки о проверке точек")
    return frame


def score(frame: pd.DataFrame) -> pd.DataFrame:
    selected = frame.loc[frame.review_status.isin(LOCATED)].copy()
    cached = {}
    values = []
    for row in selected.itertuples(index=False):
        key = row.city, row.lat, row.lon
        if key not in cached:
            try:
                forecast = evaluate_location(row.city, "coffee", row.lat, row.lon).revenue_month
            except ValueError as error:
                if not str(error).startswith(OUTSIDE_CITY):
                    raise
                cached[key] = (np.nan, np.nan, np.nan, str(error))
            else:
                annual = [getattr(forecast, level) * MONTHS_PER_YEAR for level in QUANTILES]
                cached[key] = (*annual, None)
        values.append(cached[key])
    result_columns = [*MODEL_COLUMNS, "forecast_error"]
    selected[result_columns] = pd.DataFrame(values, index=selected.index, columns=result_columns)
    selected["absolute_percentage_error"] = (selected.model_p50 / selected.revenue_rub - 1).abs()
    return selected


def metrics(frame: pd.DataFrame) -> dict:
    result = {
        "rows": len(frame),
        "organizations": int(frame.inn.nunique()),
        "mape": None,
        "bias": None,
        "coverage": None,
    }
    if frame.empty:
        return result
    actual = frame.revenue_rub
    relative = frame.model_p50 / actual
    return result | {
        "mape": float((relative - 1).abs().mean()),
        "bias": float(relative.median()),
        "coverage": float(actual.between(frame.model_p10, frame.model_p90).mean()),
    }


def grouped_metrics(frame: pd.DataFrame, cities: Iterable[str], years: Iterable[int]) -> list[dict]:
    rows = [{"city": "all", "year": None, **metrics(frame)}]
    for city in cities:
        selected = frame.loc[frame.city.eq(city)]
        rows.append({"city": city, "year": None, **metrics(selected)})
        for year in years:
            rows.append({"city": city, "year": int(year), **metrics(selected.loc[selected.year.eq(year)])})
    return rows


def compare_cogs(frame: pd.DataFrame, cities: Iterable[str]) -> list[dict]:
    raw = yaml.safe_load((research_dir() / "niche_params" / "coffee.yaml").read_text(encoding="utf-8"))
    values = []
    for city in cities:
        bounds = city_parameters(raw, city)["costs"]["cogs_share_of_revenue"]
        sample = frame.loc[frame.city.eq(city)]
        shares = (sample.cogs_rub / sample.revenue_rub).dropna()
        values.append(
            {
                "city": city,
                "rows": len(shares),
                "median": float(shares.median()) if not shares.empty else None,
                "model_range": {level: bounds[level] for level in QUANTILES},
            }
        )
    return values


def trial_adjustment(frame: pd.DataFrame) -> dict | None:
    clean = frame.loc[frame.model_p50.gt(0)]
    if clean.inn.nunique() < 2:
        return None
    ratios = clean.revenue_rub / clean.model_p50
    factors = ratios.groupby(clean.inn).median()
    scaled = clean.copy()
    for inn in factors.index:
        selected = scaled.inn.eq(inn)
        scaled.loc[selected, MODEL_COLUMNS] *= factors.drop(inn).median()
    return {
        "median_multiplier": float(factors.median()),
        "before": metrics(clean),
        "leave_one_organization_out": metrics(scaled),
    }


def plot(frame: pd.DataFrame, path: Path) -> None:
    from matplotlib import pyplot as plt

    scale = 1_000_000
    figure, axes = plt.subplots(figsize=(7.2, 5.4), layout="constrained")
    if frame.empty:
        axes.text(0.5, 0.5, "Нет точек с подтверждённым адресом", ha="center", transform=axes.transAxes)
    else:
        for status, label in (
            (ReviewStatus.VERIFIED, "Выручка одной точки"),
            (ReviewStatus.LOCATED, "Адрес точки и выручка организации"),
        ):
            selected = frame.loc[frame.review_status.eq(status)]
            if selected.empty:
                continue
            actual = selected.revenue_rub / scale
            median = selected.model_p50 / scale
            axes.errorbar(
                actual,
                median,
                yerr=[median - selected.model_p10 / scale, selected.model_p90 / scale - median],
                fmt="o",
                capsize=3,
                label=label,
            )
        end = float(max(frame.revenue_rub.max(), frame.model_p90.max())) / scale
        axes.plot([0, end], [0, end], "--", color="gray", label="Прогноз равен отчётности")
        axes.legend(loc="best")
    axes.set(
        title="Кофейни ГИР БО. Фактическая и модельная выручка",
        xlabel="Годовая выручка по отчётности, млн ₽",
        ylabel="Годовая выручка модели, млн ₽",
    )
    axes.grid(alpha=0.25)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description="Сверка прогноза кофеен с отчётностью ГИР БО")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--plot", type=Path)
    args = parser.parse_args()
    source = load_sample(args.input)
    forecasts = score(source)
    predicted = forecasts.loc[forecasts.forecast_error.isna()]
    verified = predicted.loc[predicted.review_status.eq(ReviewStatus.VERIFIED)]
    cities = ("moscow", "tula")
    years = sorted(source.year.unique())
    summary = {
        "source_statuses": source.review_status.value_counts().to_dict(),
        "outside_model_boundary_rows": int(forecasts.forecast_error.notna().sum()),
        "verified": grouped_metrics(verified, cities, years),
        "located_diagnostic": grouped_metrics(predicted, cities, years),
        "cogs_all_company_reports": compare_cogs(source, cities),
        "cogs_verified": compare_cogs(verified, cities),
        "trial_adjustment": trial_adjustment(verified),
        "diagnostic_trial_adjustment": trial_adjustment(predicted),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    forecasts.to_csv(args.output_dir / "predictions.csv", index=False)
    if args.plot:
        plot(predicted, args.plot)


if __name__ == "__main__":
    main()
