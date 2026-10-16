import argparse
import json
from pathlib import Path
from textwrap import fill
from types import ModuleType

import numpy as np

from geostart.model.validation_plots import CITY_NAMES, NICHE_NAMES, save_figure


def plotting_module() -> ModuleType:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as pyplot

    return pyplot


def plot_before_after(result: dict, output: Path) -> None:
    pyplot = plotting_module()
    rows = result["comparisons"]
    labels = [f"{CITY_NAMES[row['city']]}\n{NICHE_NAMES[row['niche']]}" for row in rows]
    positions = np.arange(len(rows))
    figure, axes = pyplot.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    for axis, metric, title, reference in zip(
        axes, ("roc_auc", "lift"), ("ROC AUC", "Lift верхних 20%"), (0.5, 1), strict=True
    ):
        axis.bar(
            positions - 0.18,
            [row["historical_before"][metric] for row in rows],
            width=0.36,
            color="#a3a3a3",
            label="S1-R4",
        )
        axis.bar(
            positions + 0.18,
            [row["after"][metric] for row in rows],
            width=0.36,
            color="#247c97",
            label="S1-R4b",
        )
        axis.axhline(reference, color="#555555", linestyle="--")
        axis.set_xticks(positions, labels)
        axis.set_ylabel(title)
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)
        axis.legend()
    axes[0].set_ylim(0, 1)
    figure.suptitle("Повторная проверка существующих точек с исключением себя")
    save_figure(figure, output, "validation_r4b_metrics")


def plot_binary_labels(result: dict, output: Path) -> None:
    pyplot = plotting_module()
    rows = result["binary_labels"]
    figure, axes = pyplot.subplots(1, 2, figsize=(10, 4.5), constrained_layout=True)
    for axis, metric, title in zip(axes, ("roc_auc", "lift"), ("ROC AUC", "Lift верхних 20%"), strict=True):
        values = np.array([row[metric] for row in rows]).reshape(2, 2)
        color = axis.imshow(
            values,
            cmap="Blues",
            vmin=0.5,
            vmax=0.8 if metric == "roc_auc" else 2.1,
        )
        axis.set_xticks([0, 1], ["Прежняя OSM", "Объединённая"])
        axis.set_yticks([0, 1], ["Модель OSM", "Модель OSM + mos_ru"])
        axis.set_xlabel("Разметка ячеек")
        axis.set_title(title)
        for row in range(2):
            for column in range(2):
                axis.text(
                    column,
                    row,
                    f"{values[row, column]:.3f}",
                    ha="center",
                    va="center",
                    fontsize=13,
                    color="white" if values[row, column] > values.mean() else "black",
                )
        figure.colorbar(color, ax=axis, shrink=0.75)
    figure.suptitle(
        "Модель и разметка раздельно, контроль фиксирован\nОбычный кандидат без исключения собственной точки"
    )
    save_figure(figure, output, "validation_r4b_labels")


def plot_seats(result: dict, output: Path) -> None:
    pyplot = plotting_module()
    figure, axes = pyplot.subplots(1, 2, figsize=(12, 4.8), constrained_layout=True)
    scenarios = result["seats"]["scenarios"]
    values = np.array([row["capture_share_distribution"] for row in scenarios]) * 100
    axes[0].bar(np.arange(3), values[:, 1], color="#247c97")
    axes[0].errorbar(
        np.arange(3),
        values[:, 1],
        yerr=[values[:, 1] - values[:, 0], values[:, 2] - values[:, 1]],
        fmt="none",
        capsize=4,
        color="#333333",
    )
    axes[0].set_xticks(np.arange(3), [str(row["seats"]) for row in scenarios])
    axes[0].set_xlabel("Число мест, остальные точки сохраняются")
    axes[0].set_ylabel("Доля доступного спроса, %")
    axes[0].set_title("Медиана и p10-p90 по 2701 расположению")
    scales = result["seat_scales"]
    axes[1].bar(np.arange(3), [row["roc_auc"] for row in scales], color=["#999999", "#247c97", "#578f42"])
    axes[1].set_xticks(np.arange(3), [f"{row['scale']:.0f}" for row in scales])
    axes[1].set_ylim(0.5, 0.8)
    for index, row in enumerate(scales):
        axes[1].text(
            index,
            row["roc_auc"] + 0.01,
            f"AUC {row['roc_auc']:.3f}\nlift {row['lift']:.3f}",
            ha="center",
            va="bottom",
        )
    axes[1].set_xlabel("Экспериментальный SEATS_SCALE")
    axes[1].set_ylabel("ROC AUC")
    axes[1].set_title("Объединённая разметка и одинаковый контроль")
    for axis in axes:
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)
    figure.suptitle("Чувствительность к посадочным местам, рабочий масштаб сохранён 20")
    save_figure(figure, output, "validation_r4b_seats")


def plot_addresses(result: dict, output: Path) -> None:
    pyplot = plotting_module()
    figure, axes = pyplot.subplots(2, 3, figsize=(18, 11), constrained_layout=True)
    for row, axis in zip(result["addresses"], axes.flat, strict=True):
        factors = row["top5"][::-1]
        effects = np.array([factor["effect_rub"] for factor in factors]) / 1000
        bars = axis.barh(
            [factor["name"] for factor in factors], effects, color=np.where(effects < 0, "#c56a39", "#247c97")
        )
        axis.bar_label(bars, labels=[f"{value:.1f}" for value in effects], padding=3, fontsize=8)
        axis.margins(x=0.2)
        axis.axvline(0, color="#555555", linewidth=0.7)
        axis.set_title(
            fill(row["address"], 35) + f"\n{row['district']} – {row['revenue_p50'] / 1e6:.2f} млн ₽/мес."
        )
        axis.set_xlabel("Эффект, тыс. ₽/месяц")
        axis.grid(axis="x", alpha=0.2)
        axis.set_axisbelow(True)
    figure.suptitle("Пять факторов на адресах из витрины, верхний ряд – центр")
    save_figure(figure, output, "validation_r4b_addresses")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Графики повторной проверки data.mos.ru")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    result = json.loads(arguments.input.read_text(encoding="utf-8"))
    plot_before_after(result, arguments.output_dir)
    plot_binary_labels(result, arguments.output_dir)
    plot_seats(result, arguments.output_dir)
    plot_addresses(result, arguments.output_dir)


if __name__ == "__main__":
    main()
