from pathlib import Path

import yaml

from geostart.config import load_cities
from geostart.settings import REPOSITORY_ROOT, config_dir

PASSPORT_PATH = REPOSITORY_ROOT / "docs" / "data-passport.md"
FIELDS = [
    ("owner", "Владелец"),
    ("url", "Где взять"),
    ("license", "Лицензия и условия"),
    ("content", "Что берём"),
    ("files", "Файлы"),
    ("coverage", "Покрытие"),
    ("version", "Версия"),
    ("update", "Как обновить"),
    ("frequency", "Частота обновления"),
]


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def formatted_number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def coverage(pipeline: dict, names: dict[str, str]) -> dict[str, str]:
    cities = pipeline["cities"]
    all_cities = ", ".join(names[code] for code in cities)
    with_mos_ru = ", ".join(names[code] for code, city in cities.items() if "mos_ru_catering" in city)
    rent = sorted(path.stem for path in (REPOSITORY_ROOT / "research" / "rent").glob("*.csv"))
    return {
        "osm": all_cities,
        "mos_ru_catering": with_mos_ru,
        "trudvsem": all_cities,
        "population": all_cities,
        "research": "параметры ниш по всем городам, ставки аренды по городам "
        + ", ".join(names.get(code, code) for code in rent),
        "basemap": all_cities,
        "geoplatform_stub": "квадраты по городам, где запускалась генерация",
    }


def versions_table(pipeline: dict, names: dict[str, str]) -> list[str]:
    extracts = pipeline["osm_extracts"]
    lines = [
        "| Город | Выгрузка OSM | Набор data.mos.ru | Регион Работы России | Численность для калибровки |",
        "| --- | --- | --- | --- | --- |",
    ]
    for code, city in pipeline["cities"].items():
        extract = extracts[city.get("extract", "central")]
        catering = city.get("mos_ru_catering")
        mos_ru = f"{catering['file']} от {catering['date']}" if catering else "–"
        scope = city.get("population_scope") or city["population_region"]
        people = formatted_number(scope["population"])
        population = f"{scope['name']}, {people} на {scope['date']}, [источник]({scope['source']})"
        osm = f"{extract['region']} от {extract['date']}"
        lines.append(f"| {names[code]} | {osm} | {mos_ru} | `{city['trudvsem_region']}` | {population} |")
    return lines


def field_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(f"`{item}`" for item in value)
    return str(value)


def render_passport() -> str:
    passport = read_yaml(config_dir() / "data_passport.yaml")
    pipeline = read_yaml(config_dir() / "pipeline.yaml")
    names = {city.code: city.name for city in load_cities()}
    covered = coverage(pipeline, names)
    lines = [
        "# Паспорт данных",
        "",
        "Документ собирается командой `uv run python -m geostart.quality passport`"
        " из `config/data_passport.yaml` и `config/pipeline.yaml`."
        " Проверки полноты и диапазонов и отчёт о качестве описаны в [quality.md](quality.md).",
        "",
        "## Источники",
        "",
        "| Источник | Владелец | Лицензия и условия | Покрытие |",
        "| --- | --- | --- | --- |",
    ]
    for source in passport["sources"]:
        lines.append(
            f"| {source['name']} | {source['owner']} | {source['license']} | {covered[source['code']]} |"
        )
    lines += ["", "## Покрытие и версии", "", *versions_table(pipeline, names)]
    for source in passport["sources"]:
        details = {**source, "coverage": covered[source["code"]]}
        lines += ["", f"## {source['name']}", "", "| Поле | Значение |", "| --- | --- |"]
        lines += [f"| {label} | {field_value(details[key])} |" for key, label in FIELDS]
    return "\n".join(lines) + "\n"


def write_passport(path: Path = PASSPORT_PATH) -> Path:
    path.write_text(render_passport(), encoding="utf-8", newline="\n")
    return path
