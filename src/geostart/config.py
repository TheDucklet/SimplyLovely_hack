from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from geostart.settings import config_dir


class CityConfig(BaseModel):
    code: str
    name: str
    osm_boundary: str
    scope: Literal["inside_mkad", "city_boundary"]
    h3_resolution: int
    center: tuple[float, float]
    zoom: int


class NicheConfig(BaseModel):
    code: str
    name: str
    osm_tags: list[dict[str, str]]
    okved: list[str]
    params_file: str


class UnknownCityError(LookupError):
    pass


class UnknownNicheError(LookupError):
    pass


def read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def load_cities() -> list[CityConfig]:
    return [CityConfig(**item) for item in read_yaml(config_dir() / "cities.yaml")["cities"]]


def load_niches() -> list[NicheConfig]:
    return [NicheConfig(**item) for item in read_yaml(config_dir() / "niches.yaml")["niches"]]


def get_city(code: str) -> CityConfig:
    cities = load_cities()
    for city in cities:
        if city.code == code:
            return city
    available = ", ".join(city.code for city in cities)
    raise UnknownCityError(f"Город {code} не найден в config/cities.yaml, доступны: {available}")


def get_niche(code: str) -> NicheConfig:
    niches = load_niches()
    for niche in niches:
        if niche.code == code:
            return niche
    available = ", ".join(niche.code for niche in niches)
    raise UnknownNicheError(f"Ниша {code} не найдена в config/niches.yaml, доступны: {available}")
