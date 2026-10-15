import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import requests
import shapely
from pydantic import BaseModel
from shapely.geometry import MultiPolygon, Polygon

from geostart.config import CityConfig, NicheConfig, get_city, load_niches, read_yaml
from geostart.pipeline import features, geometry, mos_ru, osm_extract, trudvsem
from geostart.pipeline.fixtures import ADDRESS_COLUMNS, COMPETITOR_COLUMNS, HEX_FEATURE_COLUMNS
from geostart.settings import config_dir, data_dir, processed_dir

logger = logging.getLogger("geostart.pipeline")

DOWNLOAD_CHUNK_BYTES = 1 << 20
DOWNLOAD_TIMEOUT_SECONDS = 120
INTERIM_LAYERS = ("buildings", "pois", "addresses", "boundaries", "mkad")
DISTRICT_NAME_PARTS = ("район ", " район", " территориальный округ")
EDUCATION_AMENITIES = {"school", "university", "college"}
TRANSIT_MODES = ("bus", "tram", "trolleybus")
UNKNOWN_DISTRICT = ""


class PopulationRegion(BaseModel):
    name: str
    admin_level: str
    population: int
    date: date
    source: str


class PopulationScope(BaseModel):
    name: str
    population: int
    date: date
    source: str


class CityPipelineConfig(BaseModel):
    extract_bbox: tuple[float, float, float, float]
    boundary: Literal["mkad", "admin"]
    boundary_name: str | None = None
    boundary_admin_level: str | None = None
    district_admin_level: str
    drop_empty_cells: bool
    trudvsem_region: str
    population_region: PopulationRegion
    population_scope: PopulationScope | None = None
    mos_ru_catering: mos_ru.MosRuDataset | None = None


class ExtractConfig(BaseModel):
    url: str
    file: str
    region: str
    date: date


class PipelineConfig(BaseModel):
    osm_extract: ExtractConfig
    cities: dict[str, CityPipelineConfig]


@dataclass
class StepTimer:
    durations: dict[str, float]

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        started = time.monotonic()
        yield
        self.durations[name] = round(time.monotonic() - started, 1)
        logger.info("Шаг «%s» занял %.1f с", name, self.durations[name])


def load_pipeline_config() -> PipelineConfig:
    return PipelineConfig(**read_yaml(config_dir() / "pipeline.yaml"))


def ensure_extract(extract: ExtractConfig) -> Path:
    path = data_dir() / "raw" / "osm" / extract.file
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    with requests.get(extract.url, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        response.raise_for_status()
        with partial.open("wb") as stream:
            for chunk in response.iter_content(DOWNLOAD_CHUNK_BYTES):
                stream.write(chunk)
    partial.rename(path)
    return path


def interim_dir() -> Path:
    return data_dir() / "interim" / "osm"


def ensure_layers(extract_path: Path, config: PipelineConfig) -> dict[str, pd.DataFrame]:
    target = interim_dir()
    paths = {name: target / f"{name}.parquet" for name in INTERIM_LAYERS}
    is_fresh = all(
        path.exists() and path.stat().st_mtime > extract_path.stat().st_mtime for path in paths.values()
    )
    if not is_fresh:
        boxes = {code: osm_extract.BoundingBox(*city.extract_bbox) for code, city in config.cities.items()}
        osm_extract.write_layers(osm_extract.extract_layers(extract_path, boxes), target)
    return {name: pd.read_parquet(path) for name, path in paths.items()}


def city_boundary(city_config: CityPipelineConfig, layers: dict[str, pd.DataFrame]) -> Polygon | MultiPolygon:
    if city_config.boundary == "mkad":
        return geometry.mkad_polygon(layers["mkad"])
    return geometry.admin_polygon(
        layers["boundaries"], city_config.boundary_name or "", (city_config.boundary_admin_level or "",)
    )


def with_cells(frame: pd.DataFrame, resolution: int, cells: set[str]) -> pd.DataFrame:
    located = frame.assign(
        h3=[
            h3.latlng_to_cell(lat, lon, resolution)
            for lat, lon in zip(frame["lat"], frame["lon"], strict=True)
        ]
    )
    return located[located["h3"].isin(cells)].copy()


def short_district_name(name: str) -> str:
    for part in DISTRICT_NAME_PARTS:
        name = name.replace(part, "")
    return name.strip()


def assign_districts(hexes: gpd.GeoDataFrame, boundaries: pd.DataFrame, admin_level: str) -> pd.Series:
    districts = boundaries[(boundaries["admin_level"] == admin_level) & boundaries["name"].notna()]
    district_frame = gpd.GeoDataFrame(
        {"district": districts["name"].map(short_district_name)},
        geometry=shapely.from_wkb(districts["wkb"]),
        crs=geometry.GEOGRAPHIC_CRS,
    )
    centers = geometry.points_frame(hexes[["lon", "lat"]].copy())
    joined = gpd.sjoin(centers, district_frame, how="left", predicate="within")
    return joined.groupby(level=0)["district"].first().reindex(hexes.index).fillna(UNKNOWN_DISTRICT)


def is_transit_stop(pois: pd.DataFrame) -> pd.Series:
    serves_surface_transport = pois[list(TRANSIT_MODES)].eq("yes").any(axis=1)
    return (pois["highway"] == "bus_stop") | (
        (pois["public_transport"] == "platform") & serves_surface_transport
    )


def is_metro_entrance(pois: pd.DataFrame) -> pd.Series:
    return (pois["railway"] == "subway_entrance") | (pois["station"] == "subway")


def residents_per_m2_in(
    polygon: Polygon | MultiPolygon, population: int, buildings: pd.DataFrame, label: str
) -> float:
    inside = shapely.contains_xy(polygon, buildings["lon"].to_numpy(), buildings["lat"].to_numpy())
    residential_m2 = float(features.residential_floor_area(buildings[inside]).sum())
    if residential_m2 <= 0:
        raise geometry.BoundaryNotFoundError(f"В границах «{label}» не найдено жилых зданий OSM")
    return population / residential_m2


def calibration_rate(
    city_config: CityPipelineConfig,
    buildings: pd.DataFrame,
    layers: dict[str, pd.DataFrame],
    boundary: Polygon | MultiPolygon,
) -> float:
    scope = city_config.population_scope
    if scope is not None:
        return residents_per_m2_in(boundary, scope.population, buildings, scope.name)
    region = city_config.population_region
    region_polygon = geometry.admin_polygon(layers["boundaries"], region.name, (region.admin_level,))
    return residents_per_m2_in(region_polygon, region.population, buildings, region.name)


def build_osm_hex_features(
    city: CityConfig,
    city_config: CityPipelineConfig,
    layers: dict[str, pd.DataFrame],
    boundary: Polygon | MultiPolygon,
) -> pd.DataFrame:
    cells = geometry.hex_cells(boundary, city.h3_resolution)
    hexes = geometry.hex_frame(cells).set_index("h3", drop=False)
    cell_index = pd.Index(cells, name="h3")
    region_buildings = features.classify_buildings(
        layers["buildings"][layers["buildings"]["city"] == city.code]
    )
    residents_per_m2 = calibration_rate(city_config, region_buildings, layers, boundary)
    buildings = with_cells(region_buildings, city.h3_resolution, set(cells))
    pois = with_cells(layers["pois"][layers["pois"]["city"] == city.code], city.h3_resolution, set(cells))
    residential = features.sum_by_cell(
        features.residential_floor_area(buildings), buildings["h3"], cell_index
    )
    residents = residential * residents_per_m2
    workers = features.sum_by_cell(features.worker_capacity(buildings), buildings["h3"], cell_index)
    office_buildings = features.count_by_cell(
        buildings["use"] == features.BuildingUse.OFFICE, buildings["h3"], cell_index
    )
    office_points = features.count_by_cell(
        pois["office"].notna() & pois["osm_id"].str.startswith("n"), pois["h3"], cell_index
    )
    metro_points = layers["pois"][(layers["pois"]["city"] == city.code) & is_metro_entrance(layers["pois"])]
    frame = pd.DataFrame(
        {
            "h3": cells,
            "lat": hexes["lat"].to_numpy(),
            "lon": hexes["lon"].to_numpy(),
            "district": assign_districts(
                hexes, layers["boundaries"], city_config.district_admin_level
            ).to_numpy(),
            "residents": residents.round(1).to_numpy(),
            "workers": workers.round(1).to_numpy(),
            "offices_n": (office_buildings + office_points).to_numpy(),
            "education_n": features.count_by_cell(
                pois["amenity"].isin(EDUCATION_AMENITIES), pois["h3"], cell_index
            ).to_numpy(),
            "malls_n": features.count_by_cell(pois["shop"] == "mall", pois["h3"], cell_index).to_numpy(),
            "transit_stops_n": features.count_by_cell(
                is_transit_stop(pois), pois["h3"], cell_index
            ).to_numpy(),
            "metro_dist_m": features.nearest_distance_m(
                hexes.reset_index(drop=True), metro_points
            ).to_numpy(),
        }
    )
    if city_config.drop_empty_cells:
        built_area = features.sum_by_cell(buildings["floor_area_m2"], buildings["h3"], cell_index)
        frame = frame[built_area.to_numpy() > 0]
    return frame[HEX_FEATURE_COLUMNS].reset_index(drop=True)


def matches_tag_rule(pois: pd.DataFrame, rule: dict[str, str]) -> pd.Series:
    mask = pd.Series(True, index=pois.index)
    for key, value in rule.items():
        column = pois[key].fillna("") if key in pois else pd.Series("", index=pois.index)
        if key == "cuisine":
            mask &= column.str.split(";").apply(
                lambda values, wanted=value: wanted in [v.strip() for v in values]
            )
        else:
            mask &= column == value
    return mask


def build_osm_competitors(
    city: CityConfig, niches: list[NicheConfig], pois: pd.DataFrame, cells: set[str]
) -> pd.DataFrame:
    located = with_cells(pois[pois["city"] == city.code], city.h3_resolution, cells)
    frames = []
    for niche in niches:
        mask = pd.Series(False, index=located.index)
        for rule in niche.osm_tags:
            mask |= matches_tag_rule(located, rule)
        for name_rule in niche.osm_name_rules:
            label = located["name"].fillna("") + " " + located["brand"].fillna("")
            mask |= matches_tag_rule(located, name_rule.tags) & label.str.contains(
                name_rule.pattern, regex=True
            )
        selected = located[mask]
        frames.append(
            pd.DataFrame(
                {
                    "poi_id": selected["osm_id"],
                    "niche": niche.code,
                    "name": selected["name"].fillna(f"{niche.name} без названия"),
                    "brand": selected["brand"].astype(object).where(selected["brand"].notna(), None),
                    "lat": selected["lat"].round(6),
                    "lon": selected["lon"].round(6),
                    "h3": selected["h3"],
                    "source": "osm",
                    "seats": pd.array([pd.NA] * len(selected), dtype="Int64"),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)[COMPETITOR_COLUMNS]


def build_mos_ru_competitors(
    city: CityConfig, niches: list[NicheConfig], catering: pd.DataFrame, cells: set[str]
) -> pd.DataFrame:
    located = with_cells(catering, city.h3_resolution, cells)
    frames = [
        mos_ru.select_by_name(located, niche.mos_ru_name_pattern).assign(niche=niche.code, source="mos_ru")
        for niche in niches
        if niche.mos_ru_name_pattern
    ]
    if not frames:
        return pd.DataFrame(columns=COMPETITOR_COLUMNS)
    combined = pd.concat(frames, ignore_index=True)
    return combined.assign(lat=combined["lat"].round(6), lon=combined["lon"].round(6))[COMPETITOR_COLUMNS]


def combine_competitors(osm: pd.DataFrame, official: pd.DataFrame) -> pd.DataFrame:
    frames = [
        mos_ru.merge_competitors(osm[osm["niche"] == niche], official[official["niche"] == niche])
        for niche in pd.unique(pd.concat([osm["niche"], official["niche"]]))
    ]
    combined = pd.concat(frames, ignore_index=True)
    return combined.assign(seats=combined["seats"].astype("Int64"))[COMPETITOR_COLUMNS]


def build_osm_addresses(city: CityConfig, addresses: pd.DataFrame, cells: set[str]) -> pd.DataFrame:
    located = with_cells(addresses[addresses["city"] == city.code], city.h3_resolution, cells)
    located["address"] = located["street"].str.strip() + ", " + located["housenumber"].str.strip()
    located = located.drop_duplicates("address")
    return located.assign(lat=located["lat"].round(6), lon=located["lon"].round(6))[
        ADDRESS_COLUMNS
    ].reset_index(drop=True)


def run_city(city_code: str, collected_at: date | None = None) -> dict[str, float | int]:
    timer = StepTimer(durations={})
    city = get_city(city_code)
    config = load_pipeline_config()
    city_config = config.cities[city_code]
    with timer.step("выгрузка OSM"):
        extract_path = ensure_extract(config.osm_extract)
    with timer.step("извлечение слоёв OSM"):
        layers = ensure_layers(extract_path, config)
    with timer.step("граница города"):
        boundary = city_boundary(city_config, layers)
    with timer.step("признаки ячеек"):
        hex_features = build_osm_hex_features(city, city_config, layers, boundary)
    cells = set(hex_features["h3"])
    with timer.step("конкуренты"):
        niches = load_niches()
        competitors = build_osm_competitors(city, niches, layers["pois"], cells)
        osm_coffee = int((competitors["niche"] == "coffee").sum())
        if city_config.mos_ru_catering is not None:
            dataset_path = mos_ru.ensure_dataset(city_config.mos_ru_catering, data_dir() / "raw" / "mos_ru")
            catering = mos_ru.catering_frame(mos_ru.read_records(dataset_path))
            competitors = combine_competitors(
                competitors, build_mos_ru_competitors(city, niches, catering, cells)
            )
    with timer.step("адреса"):
        addresses = build_osm_addresses(city, layers["addresses"], cells)
    with timer.step("зарплаты"):
        wages = trudvsem.build_wages(
            city_config.trudvsem_region, data_dir() / "raw" / "trudvsem", collected_at or date.today()
        )
    target = processed_dir(city_code)
    target.mkdir(parents=True, exist_ok=True)
    hex_features.to_parquet(target / "hex_features.parquet", index=False)
    competitors.to_parquet(target / "competitors.parquet", index=False)
    wages.to_parquet(target / "wages.parquet", index=False)
    addresses.to_parquet(target / "addresses.parquet", index=False)
    gpd.GeoSeries([boundary], crs=geometry.GEOGRAPHIC_CRS).to_file(
        target / "boundary.geojson", driver="GeoJSON"
    )
    return {
        "cells": len(hex_features),
        "residents": round(float(hex_features["residents"].sum())),
        "workers": round(float(hex_features["workers"].sum())),
        "competitors_coffee": int((competitors["niche"] == "coffee").sum()),
        "competitors_coffee_osm_only": osm_coffee,
        "competitors_mos_ru": int((competitors["source"] == "mos_ru").sum()),
        "competitors_pickup_point": int((competitors["niche"] == "pickup_point").sum()),
        "addresses": len(addresses),
        "metro_cells_within_1km": int((hex_features["metro_dist_m"] <= 1000).sum()),
        "unknown_district_cells": int((hex_features["district"] == UNKNOWN_DISTRICT).sum()),
        **{f"seconds_{name}": value for name, value in timer.durations.items()},
        "boundary_area_km2": round(
            float(
                gpd.GeoSeries([boundary], crs=geometry.GEOGRAPHIC_CRS)
                .to_crs(geometry.METRIC_CRS)
                .area.iloc[0]
            )
            / 1e6,
            1,
        ),
        "wage_rows": len(wages),
        "empty_residents_share": round(float(np.mean(hex_features["residents"] == 0)), 3),
    }
