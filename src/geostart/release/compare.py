from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import yaml

from geostart.settings import config_dir

CITY_LABELS = {
    "cells": "ячеек",
    "boundary_area_km2": "площадь границы, км²",
    "residents": "жителей",
    "workers": "работающих",
    "addresses": "адресов",
    "wage_rows": "строк зарплат",
}
SCORE_LABELS = {
    "cells": "ячеек",
    "revenue_p50_median": "медиана выручки p50",
    "revenue_p50_p90": "90-й процентиль выручки p50",
    "profit_p50_median": "медиана прибыли p50",
    "payback_months_p50_median": "медиана окупаемости p50",
}


@dataclass(frozen=True)
class Check:
    scope: str
    metric: str
    previous: float | None
    current: float | None
    change: float | None
    limit: float
    passed: bool
    note: str = ""


def load_thresholds(path: Path | None = None) -> dict:
    return yaml.safe_load((path or config_dir() / "release.yaml").read_text(encoding="utf-8"))


def relative(previous: float, current: float, floor: float) -> float:
    return abs(current - previous) / max(abs(previous), floor, 1e-9)


def metric_check(
    scope: str, metric: str, previous: object, current: object, limit: float, floor: float = 0
) -> Check:
    if previous is None and current is None:
        return Check(scope, metric, None, None, None, limit, True, "нет значения в обеих версиях")
    if previous is None or current is None:
        return Check(scope, metric, previous, current, None, limit, False, "значение появилось или пропало")
    change = relative(float(previous), float(current), floor)
    return Check(scope, metric, float(previous), float(current), round(change, 4), limit, change <= limit)


def city_checks(code: str, previous: dict, current: dict, thresholds: dict) -> list[Check]:
    limits, floors = thresholds["city"], thresholds.get("floors", {})
    checks = [
        metric_check(code, label, previous.get(key), current.get(key), limits[key], floors.get(key, 0))
        for key, label in CITY_LABELS.items()
        if key in limits and (key in previous or key in current)
    ]
    for niche in sorted(set(previous["competitors"]) | set(current["competitors"])):
        checks.append(
            metric_check(
                code,
                f"конкурентов {niche}",
                previous["competitors"].get(niche),
                current["competitors"].get(niche),
                limits["competitors"],
                floors.get("competitors", 0),
            )
        )
    return checks


def score_checks(key: str, previous: dict, current: dict, thresholds: dict) -> list[Check]:
    limits, floors = thresholds["score"], thresholds.get("floors", {})
    checks = [
        metric_check(key, label, previous.get(name), current.get(name), limits[name], floors.get(name, 0))
        for name, label in SCORE_LABELS.items()
    ]
    for level, share in previous["risk_share"].items():
        now = current["risk_share"].get(level, 0.0)
        change = round(abs(now - share), 4)
        checks.append(
            Check(
                key,
                f"доля риска {level}",
                share,
                now,
                change,
                limits["risk_share"],
                change <= limits["risk_share"],
            )
        )
    return checks


def cell_check(key: str, previous_path: Path, current_path: Path, thresholds: dict) -> Check:
    limits = thresholds["cells"]
    previous = pd.read_parquet(previous_path, columns=["h3", "revenue_p50"])
    current = pd.read_parquet(current_path, columns=["h3", "revenue_p50"])
    joined = previous.merge(current, on="h3", suffixes=("_old", "_new"))
    if joined.empty:
        return Check(
            key, "доля ячеек с сильным изменением выручки", None, None, None, limits["changed_share"], False
        )
    base = joined["revenue_p50_old"].abs().clip(lower=1.0)
    changed = ((joined["revenue_p50_new"] - joined["revenue_p50_old"]).abs() / base) > limits[
        "revenue_change"
    ]
    share = round(float(changed.mean()), 4)
    return Check(
        key,
        "доля ячеек с сильным изменением выручки",
        None,
        share,
        share,
        limits["changed_share"],
        share <= limits["changed_share"],
        f"порог изменения ячейки {limits['revenue_change']:.0%}, общих ячеек {len(joined)}",
    )


def compare(
    previous: dict,
    current: dict,
    thresholds: dict,
    previous_root: Path | None = None,
    current_root: Path | None = None,
    cities: set[str] | None = None,
) -> list[Check]:
    checks: list[Check] = []
    for code in sorted(set(previous["cities"]) | set(current["cities"])):
        if cities is not None and code not in cities:
            continue
        before, after = previous["cities"].get(code), current["cities"].get(code)
        if before is None:
            checks.append(Check(code, "город", None, None, None, 0, True, "новый город"))
        elif after is None:
            checks.append(Check(code, "город", None, None, None, 0, False, "город пропал из данных"))
        else:
            checks.extend(city_checks(code, before, after, thresholds))
    for key in sorted(set(previous["scores"]) | set(current["scores"])):
        if cities is not None and key.split("/")[0] not in cities:
            continue
        before, after = previous["scores"].get(key), current["scores"].get(key)
        if before is None:
            checks.append(Check(key, "расчёт", None, None, None, 0, True, "новый расчёт"))
            continue
        if after is None:
            checks.append(Check(key, "расчёт", None, None, None, 0, False, "расчёт пропал"))
            continue
        checks.extend(score_checks(key, before, after, thresholds))
        if previous_root is not None and current_root is not None:
            name = key.replace("/", "_") + ".parquet"
            old_path, new_path = previous_root / "scores" / name, current_root / "scores" / name
            if old_path.exists() and new_path.exists():
                checks.append(cell_check(key, old_path, new_path, thresholds))
    return checks


def failed(checks: list[Check]) -> list[Check]:
    return [check for check in checks if not check.passed]


def value(number: float | None) -> str:
    if number is None:
        return "–"
    return f"{number:,.2f}".replace(",", " ").replace(".", ",").removesuffix(",00")


def render(previous: dict, current: dict, checks: list[Check]) -> str:
    problems = failed(checks)
    verdict = "расхождения в пределах порогов" if not problems else f"выше порогов {len(problems)} проверок"
    lines = [
        f"# Сравнение данных {current['version']} с {previous['version']}",
        "",
        f"Итог – {verdict}, всего проверок {len(checks)}.",
        "",
        "| Город или расчёт | Показатель | Было | Стало | Изменение | Порог | Итог |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for check in sorted(checks, key=lambda item: (item.passed, item.scope, item.metric)):
        change = "–" if check.change is None else f"{check.change:.1%}".replace(".", ",")
        limit = f"{check.limit:.0%}" if check.limit else "–"
        status = "норма" if check.passed else "выше порога"
        note = f" ({check.note})" if check.note else ""
        lines.append(
            f"| {check.scope} | {check.metric}{note} | {value(check.previous)} | {value(check.current)} "
            f"| {change} | {limit} | {status} |"
        )
    return "\n".join(lines) + "\n"


def as_json(checks: list[Check]) -> list[dict]:
    return [asdict(check) for check in checks]
