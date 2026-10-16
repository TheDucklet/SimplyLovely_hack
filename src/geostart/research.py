from collections.abc import Iterable, Mapping
from typing import Any

from geostart.config import load_cities

CITY_SECTIONS = ("demand", "costs", "benchmarks")


def split_city_suffix(key: str, city_codes: Iterable[str]) -> tuple[str, str | None]:
    for code in city_codes:
        suffix = f"_{code}"
        if key.endswith(suffix) and len(key) > len(suffix):
            return key[: -len(suffix)], code
    return key, None


def resolve_block(block: Mapping[str, Any], city: str, city_codes: tuple[str, ...]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    overrides: dict[str, Any] = {}
    for key, value in block.items():
        base, code = split_city_suffix(key, city_codes)
        if code is None:
            resolved.setdefault(key, value)
        elif code == city:
            overrides[base] = value
    resolved.update(overrides)
    return resolved


def city_parameters(raw: Mapping[str, Any], city: str) -> dict[str, Any]:
    city_codes = tuple(item.code for item in load_cities())
    parameters = resolve_block(raw, city, city_codes)
    for section in CITY_SECTIONS:
        if isinstance(parameters.get(section), Mapping):
            parameters[section] = resolve_block(parameters[section], city, city_codes)
    return parameters
