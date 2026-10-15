import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CITY_NAMES = {"moscow": "Москва", "tula": "Тула"}
NICHE_NAMES = {"coffee": "Кофейни", "pickup_point": "Пункты выдачи"}
PARAMETER_NAMES = {
    "avg_check_rub": "Средний чек",
    "visits_per_resident_month": "Посещения жителей",
    "visits_per_worker_month": "Посещения работников",
    "orders_per_resident_month": "Заказы жителей",
    "marketplace_share": "Доля заказов",
    "payout_per_order_rub": "Выплата за заказ",
    "max_walk_distance_m": "Радиус",
    "distance_decay_beta": "Степень расстояния",
    "outside_option_weight": "Внешняя альтернатива",
}


def save_figure(figure: plt.Figure, output: Path, name: str) -> None:
    figure.savefig(output / f"{name}.png", dpi=180, bbox_inches="tight")
    vector_path = output / f"{name}.svg"
    figure.savefig(vector_path, bbox_inches="tight")
    content = vector_path.read_text(encoding="utf-8")
    vector_path.write_text("\n".join(line.rstrip() for line in content.splitlines()) + "\n", encoding="utf-8")
    plt.close(figure)


def plot_metrics(results: list[dict], output: Path) -> None:
    labels = [f"{CITY_NAMES[item['city']]}\n{NICHE_NAMES[item['niche']]}" for item in results]
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    positions = np.arange(len(results))
    axes[0].bar(positions, [item["validation"]["roc_auc"] for item in results], color="#247c97")
    axes[0].axhline(0.5, color="#555555", linestyle="--", label="Случайное ранжирование")
    axes[0].set_ylim(0, 1)
    axes[0].set_ylabel("ROC AUC")
    axes[0].legend(loc="lower left", fontsize=8)
    axes[1].bar(positions, [item["validation"]["lift"] for item in results], color="#578f42")
    axes[1].axhline(1, color="#555555", linestyle="--", label="Случайная доля")
    axes[1].set_ylabel("Lift верхних 20% ячеек")
    axes[1].legend(fontsize=8)
    for axis in axes:
        axis.set_xticks(positions, labels)
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)
    figure.suptitle("Потенциал существующих точек без собственного конкурента")
    save_figure(figure, output, "validation_r4_metrics")


def plot_sensitivity(results: list[dict], output: Path) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)
    for result, axis in zip(results, axes.flat, strict=True):
        sensitivity = pd.DataFrame(result["sensitivity"]).head(5).iloc[::-1]
        names = [PARAMETER_NAMES.get(name, name) for name in sensitivity.parameter]
        values = sensitivity.city_median_change_pct.to_numpy()
        axis.barh(names, values, color=np.where(values >= 0, "#247c97", "#c56a39"))
        axis.axvline(0, color="#777777", linewidth=0.7)
        axis.set_title(f"{CITY_NAMES[result['city']]} – {NICHE_NAMES[result['niche']]}")
        axis.set_xlabel("Изменение медианы выручки, % от базового уровня")
        axis.grid(axis="x", alpha=0.2)
        axis.set_axisbelow(True)
    figure.suptitle("Параметр меняется от p10 до p90, остальные прогоны сохраняются")
    save_figure(figure, output, "validation_r4_sensitivity")


def plot_pickup_scale(results: list[dict], output: Path) -> None:
    pickups = [item for item in results if item["niche"] == "pickup_point"]
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.5), constrained_layout=True)
    for result, axis in zip(pickups, axes, strict=True):
        distributions = [
            result["before"]["revenue_distribution"],
            result["revenue_distribution"],
            result["unapproved_scenario"]["revenue_distribution"],
        ]
        medians = np.array([values[1] for values in distributions]) / 1000
        lower = np.array([values[0] for values in distributions]) / 1000
        upper = np.array([values[2] for values in distributions]) / 1000
        axis.bar(np.arange(3), medians, color=["#999999", "#247c97", "#c56a39"])
        axis.errorbar(
            np.arange(3),
            medians,
            yerr=[medians - lower, upper - medians],
            fmt="none",
            color="#222222",
            capsize=4,
        )
        axis.set_xticks(np.arange(3), ["До", "Исправленная\nальтернатива", "Условный\nсценарий"])
        axis.set_ylabel("Выручка p50 по ячейкам, тыс. ₽/месяц")
        axis.set_title(CITY_NAMES[result["city"]])
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)
    figure.suptitle("Медиана и диапазон p10-p90 по ячейкам, сценарий не принят в модель")
    save_figure(figure, output, "validation_r4_pickup_scale")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Графики проверки модели ГеоСтарта")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    results = json.loads(arguments.input.read_text(encoding="utf-8"))
    plot_metrics(results, arguments.output_dir)
    plot_sensitivity(results, arguments.output_dir)
    plot_pickup_scale(results, arguments.output_dir)


if __name__ == "__main__":
    main()
