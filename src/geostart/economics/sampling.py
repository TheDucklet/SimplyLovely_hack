from collections.abc import Mapping

import numpy as np

LOWER_LEVEL = 0.1
MIDDLE_LEVEL = 0.5
UPPER_LEVEL = 0.9
QUANTILE_LEVELS = (LOWER_LEVEL, MIDDLE_LEVEL, UPPER_LEVEL)


def check_estimate(name: str, p10: float, p50: float, p90: float) -> None:
    values = np.array([p10, p50, p90], dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError(f"Оценка {name} должна быть конечной и неотрицательной")
    if not p10 <= p50 <= p90:
        raise ValueError(f"В оценке {name} должно выполняться p10 ≤ p50 ≤ p90")


def stratified_levels(runs: int, generator: np.random.Generator) -> np.ndarray:
    if runs <= 0:
        raise ValueError("Число сценариев должно быть положительным")
    return generator.permutation((np.arange(runs) + 0.5) / runs)


def quantile_samples(
    name: str, p10: float, p50: float, p90: float, runs: int, generator: np.random.Generator
) -> np.ndarray:
    check_estimate(name, p10, p50, p90)
    levels = stratified_levels(runs, generator)
    lower_slope = (p50 - p10) / (MIDDLE_LEVEL - LOWER_LEVEL)
    upper_slope = (p90 - p50) / (UPPER_LEVEL - MIDDLE_LEVEL)
    values = np.where(
        levels < MIDDLE_LEVEL,
        p50 - (MIDDLE_LEVEL - levels) * lower_slope,
        p50 + (levels - MIDDLE_LEVEL) * upper_slope,
    )
    return np.maximum(values, 0.0)


def bounds_samples(
    name: str, bounds: Mapping[str, object], runs: int, generator: np.random.Generator
) -> np.ndarray:
    return quantile_samples(
        name, float(bounds["p10"]), float(bounds["p50"]), float(bounds["p90"]), runs, generator
    )


def summary(values: np.ndarray) -> tuple[float, float, float]:
    p10, p50, p90 = np.quantile(values, QUANTILE_LEVELS)
    return float(p10), float(p50), float(p90)


def optional_summary(
    values: np.ndarray, *, missing_high: bool = True
) -> tuple[float | None, float | None, float | None]:
    missing = np.inf if missing_high else -np.inf
    filled = np.where(np.isfinite(values), values, missing)
    with np.errstate(invalid="ignore"):
        quantiles = np.quantile(filled, QUANTILE_LEVELS)
    quantiles = np.where(np.isnan(quantiles), missing, quantiles)
    return tuple(float(value) if np.isfinite(value) else None for value in quantiles)
