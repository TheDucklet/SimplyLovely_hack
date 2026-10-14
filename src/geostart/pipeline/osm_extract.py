import contextlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import osmium
import pandas as pd

logger = logging.getLogger(__name__)

AREA_KEYS = ("building", "boundary", "amenity", "shop", "office")
TAGGED_KEYS = (
    "building",
    "boundary",
    "amenity",
    "shop",
    "office",
    "public_transport",
    "highway",
    "railway",
    "station",
    "addr:housenumber",
)
POI_TAGS = (
    "amenity",
    "shop",
    "office",
    "cuisine",
    "brand",
    "name",
    "public_transport",
    "highway",
    "railway",
    "station",
    "bus",
    "tram",
    "trolleybus",
)
BUILDING_TAGS = ("building", "building:levels", "name", "amenity", "shop", "office")
ADDRESS_TAGS = ("addr:street", "addr:housenumber")
BOUNDARY_TAGS = ("name", "admin_level", "population", "boundary")
MKAD_MARKERS = ("МКАД", "Московская кольцевая")
MKAD_HIGHWAYS = {"motorway", "trunk"}
REGIONAL_ADMIN_LEVELS = {"4", "5", "6", "9"}
PROGRESS_EVERY = 5_000_000


@dataclass(frozen=True)
class BoundingBox:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    def contains(self, lon: float, lat: float) -> bool:
        return self.min_lon <= lon <= self.max_lon and self.min_lat <= lat <= self.max_lat


@dataclass
class ExtractedLayers:
    buildings: list[dict] = field(default_factory=list)
    pois: list[dict] = field(default_factory=list)
    addresses: list[dict] = field(default_factory=list)
    boundaries: list[dict] = field(default_factory=list)
    mkad: list[dict] = field(default_factory=list)


def city_of(boxes: dict[str, BoundingBox], lon: float, lat: float) -> str | None:
    for city_code, box in boxes.items():
        if box.contains(lon, lat):
            return city_code
    return None


def pick_tags(tags: osmium.osm.TagList, keys: tuple[str, ...]) -> dict[str, str | None]:
    return {key: tags.get(key) for key in keys}


def has_poi_tags(tags: osmium.osm.TagList) -> bool:
    return any(
        key in tags for key in ("amenity", "shop", "office", "public_transport", "railway", "station")
    ) or (tags.get("highway") == "bus_stop")


def address_record(city_code: str, tags: osmium.osm.TagList, lon: float, lat: float) -> dict | None:
    street = tags.get("addr:street")
    house = tags.get("addr:housenumber")
    if not street or not house:
        return None
    return {"city": city_code, "street": street, "housenumber": house, "lon": lon, "lat": lat}


def is_mkad(tags: osmium.osm.TagList) -> bool:
    if tags.get("highway") not in MKAD_HIGHWAYS:
        return False
    text = f"{tags.get('name', '')} {tags.get('ref', '')}"
    return any(marker in text for marker in MKAD_MARKERS)


def area_anchor(area: osmium.osm.Area) -> tuple[float, float] | None:
    for ring in area.outer_rings():
        for node in ring:
            if node.location.valid():
                return node.location.lon, node.location.lat
    return None


def handle_node(node: osmium.osm.Node, boxes: dict[str, BoundingBox], layers: ExtractedLayers) -> None:
    lon, lat = node.location.lon, node.location.lat
    city_code = city_of(boxes, lon, lat)
    if city_code is None:
        return
    if has_poi_tags(node.tags):
        layers.pois.append(
            {
                "city": city_code,
                "osm_id": f"n{node.id}",
                "lon": lon,
                "lat": lat,
                **pick_tags(node.tags, POI_TAGS),
            }
        )
    address = address_record(city_code, node.tags, lon, lat)
    if address:
        layers.addresses.append(address)


def handle_way(way: osmium.osm.Way, boxes: dict[str, BoundingBox], layers: ExtractedLayers) -> None:
    if not is_mkad(way.tags):
        return
    coordinates = [(node.lon, node.lat) for node in way.nodes if node.location.valid()]
    if len(coordinates) < 2 or city_of(boxes, *coordinates[0]) is None:
        return
    layers.mkad.append({"osm_id": f"w{way.id}", "coordinates": coordinates})


def handle_area(
    area: osmium.osm.Area,
    boxes: dict[str, BoundingBox],
    layers: ExtractedLayers,
    factory: osmium.geom.WKBFactory,
) -> None:
    tags = area.tags
    is_boundary = tags.get("boundary") == "administrative"
    anchor = area_anchor(area)
    if anchor is None:
        return
    city_code = city_of(boxes, *anchor)
    if city_code is None and not (is_boundary and tags.get("admin_level") in REGIONAL_ADMIN_LEVELS):
        return
    try:
        geometry = factory.create_multipolygon(area)
    except RuntimeError:
        return
    source_id = f"{'w' if area.from_way() else 'r'}{area.orig_id()}"
    if is_boundary:
        layers.boundaries.append(
            {
                "osm_id": source_id,
                "anchor_city": city_code,
                "wkb": bytes.fromhex(geometry),
                **pick_tags(tags, BOUNDARY_TAGS),
            }
        )
        return
    if "building" in tags:
        layers.buildings.append(
            {
                "city": city_code,
                "osm_id": source_id,
                "wkb": bytes.fromhex(geometry),
                **pick_tags(tags, BUILDING_TAGS),
            }
        )
    if has_poi_tags(tags):
        layers.pois.append(
            {
                "city": city_code,
                "osm_id": source_id,
                "lon": anchor[0],
                "lat": anchor[1],
                "wkb": bytes.fromhex(geometry),
                **pick_tags(tags, POI_TAGS),
            }
        )
    address = address_record(city_code, tags, *anchor)
    if address:
        layers.addresses.append(address)


def extract_layers(extract_path: Path, boxes: dict[str, BoundingBox]) -> ExtractedLayers:
    layers = ExtractedLayers()
    factory = osmium.geom.WKBFactory()
    started = time.monotonic()
    with contextlib.chdir(extract_path.resolve().parent):
        processor = (
            osmium.FileProcessor(extract_path.name)
            .with_locations()
            .with_areas(osmium.filter.KeyFilter(*AREA_KEYS))
            .with_filter(osmium.filter.KeyFilter(*TAGGED_KEYS))
        )
        for index, entity in enumerate(processor, start=1):
            if entity.is_area():
                handle_area(entity, boxes, layers, factory)
            elif entity.is_node():
                handle_node(entity, boxes, layers)
            elif entity.is_way():
                handle_way(entity, boxes, layers)
            if index % PROGRESS_EVERY == 0:
                logger.info("Обработано %s объектов OSM за %.0f с", index, time.monotonic() - started)
    logger.info("Извлечение OSM заняло %.0f с", time.monotonic() - started)
    return layers


def write_layers(layers: ExtractedLayers, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(layers.buildings).to_parquet(target_dir / "buildings.parquet", index=False)
    pd.DataFrame(layers.pois).to_parquet(target_dir / "pois.parquet", index=False)
    pd.DataFrame(layers.addresses).to_parquet(target_dir / "addresses.parquet", index=False)
    pd.DataFrame(layers.boundaries).to_parquet(target_dir / "boundaries.parquet", index=False)
    pd.DataFrame(layers.mkad).to_parquet(target_dir / "mkad.parquet", index=False)
