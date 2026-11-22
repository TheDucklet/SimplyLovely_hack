from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

from geostart.config import get_city
from geostart.quality.checks import ERROR, Result, errors, warnings
from geostart.release.manifest import build_manifest

COMPLETENESS = [
    ("hex_features.parquet", "district", "район ячейки", lambda column: column.fillna("") != ""),
    ("hex_features.parquet", "metro_dist_m", "расстояние до метро", lambda column: column.notna()),
    ("competitors.parquet", "brand", "сеть конкурента", lambda column: column.notna()),
    ("competitors.parquet", "seats", "посадочные места", lambda column: column.notna()),
]


def number(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def percent(value: float) -> str:
    return f"{value:.0%}"


def completeness_table(root: Path, cities: list[str]) -> list[str]:
    header = "| Город | " + " | ".join(label for _, _, label, _ in COMPLETENESS) + " |"
    lines = [header, "| --- |" + " ---: |" * len(COMPLETENESS)]
    for code in cities:
        cells = []
        for file, column, _, filled in COMPLETENESS:
            frame = pd.read_parquet(root / "processed" / code / file, columns=[column])
            cells.append(percent(float(filled(frame[column]).mean())) if len(frame) else "–")
        lines.append(f"| {get_city(code).name} | " + " | ".join(cells) + " |")
    return lines


def summary_table(manifest: dict, results: list[Result], cities: list[str]) -> list[str]:
    lines = [
        "| Город | Ячеек | Жителей | Конкурентов | Адресов | Зарплаты на "
        "| Проверок | Ошибок | Предупреждений |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for code in cities:
        city = manifest["cities"].get(code, {})
        own = [result for result in results if result.city == code]
        lines.append(
            f"| {get_city(code).name} | {number(city.get('cells', 0))} | {number(city.get('residents', 0))} "
            f"| {number(sum(city.get('competitors', {}).values()))} | {number(city.get('addresses', 0))} "
            f"| {city.get('wages_collected_at') or '–'} | {len(own)} "
            f"| {len(errors(own))} | {len(warnings(own))} |"
        )
    return lines


def checks_table(results: list[Result]) -> list[str]:
    grouped: dict[tuple[str, str, str], list[Result]] = defaultdict(list)
    for result in results:
        dataset = "scores" if result.dataset.startswith("scores/") else result.dataset
        grouped[(dataset, result.check, result.severity)].append(result)
    lines = ["| Набор | Проверка | Уровень | Прошли | Не прошли |", "| --- | --- | --- | ---: | --- |"]
    for (dataset, check, severity), items in grouped.items():
        failed = sorted({get_city(item.city).name for item in items if not item.passed})
        level = "ошибка" if severity == ERROR else "предупреждение"
        passed = sum(item.passed for item in items)
        lines.append(f"| {dataset} | {check} | {level} | {passed} | {', '.join(failed) or '–'} |")
    return lines


def render_report(root: Path, results: list[Result], checked_on: date | None = None) -> str:
    manifest = build_manifest(root)
    cities = list(dict.fromkeys(result.city for result in results))
    problems = errors(results)
    notes = warnings(results)
    verdict = "ошибок нет" if not problems else f"ошибок {len(problems)}, версия не готова к выпуску"
    lines = [
        "# Отчёт о качестве данных",
        "",
        f"Версия данных `{manifest['version']}`, проверка {(checked_on or date.today()).isoformat()}. "
        f"Проверок выполнено {len(results)} по {len(cities)} городам, {verdict},"
        f" предупреждений {len(notes)}. Правила проверок и пороги описаны в `docs/quality.md`"
        " и `config/quality.yaml`, источники в `docs/data-passport.md`.",
        "",
        "## Сводка по городам",
        "",
        *summary_table(manifest, results, cities),
        "",
        "## Заполненность необязательных полей",
        "",
        "Пустые значения в этих полях допустимы. Метро есть не во всех городах, посадочные места и сеть"
        " публикует только портал data.mos.ru, а OSM указывает их выборочно.",
        "",
        *completeness_table(root, cities),
        "",
        "## Замечания",
        "",
    ]
    if not problems and not notes:
        lines.append("Замечаний нет.")
    for result in [*problems, *notes]:
        level = "Ошибка" if result.severity == ERROR else "Предупреждение"
        detail = f", {result.detail}" if result.detail else ""
        lines.append(f"- {level}. {get_city(result.city).name}, `{result.dataset}`, {result.check}{detail}.")
    lines += ["", "## Проверки", "", *checks_table(results)]
    return "\n".join(lines) + "\n"
