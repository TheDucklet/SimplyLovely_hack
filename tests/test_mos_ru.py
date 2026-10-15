import json
import zipfile
from pathlib import Path

import h3
import pandas as pd

from geostart.config import CityConfig, NicheConfig
from geostart.pipeline import mos_ru, run
from geostart.pipeline.fixtures import COMPETITOR_COLUMNS

CENTER = (55.7558, 37.6176)
METERS_PER_DEGREE_LAT = 111_320
COFFEE_PATTERN = "(?i)коф|coffee"


def record(global_id: int, name: str, lat: float, lon: float, **extra: object) -> dict:
    return {
        "ID": str(global_id),
        "Name": name,
        "global_id": global_id,
        "IsNetObject": "нет",
        "OperatingCompany": "",
        "TypeObject": "кафе",
        "SeatsCount": 10,
        "Longitude_WGS84": str(lon),
        "Latitude_WGS84": str(lat),
        "PublicPhone": [{"PublicPhone": "(495) 000-00-00"}],
        **extra,
    }


def shifted(meters_north: float) -> float:
    return CENTER[0] + meters_north / METERS_PER_DEGREE_LAT


def write_archive(path: Path, records: list[dict]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data-1903.json", "﻿" + json.dumps(records, ensure_ascii=False))
    return path


def competitor(poi_id: str, niche: str, lat: float, source: str = "osm") -> dict:
    return {
        "poi_id": poi_id,
        "niche": niche,
        "name": poi_id,
        "brand": None,
        "lat": lat,
        "lon": CENTER[1],
        "h3": h3.latlng_to_cell(lat, CENTER[1], 9),
        "source": source,
        "seats": pd.NA,
    }


def test_read_records_keeps_no_phones(tmp_path: Path) -> None:
    path = write_archive(tmp_path / "data.zip", [record(1, "Кофейня «Утро»", *CENTER)])
    records = mos_ru.read_records(path)
    assert records[0]["Name"] == "Кофейня «Утро»"
    assert "PublicPhone" not in records[0]


def test_catering_frame_parses_brand_seats_and_coordinates() -> None:
    frame = mos_ru.catering_frame(
        [
            record(1, "Cofix", *CENTER, IsNetObject="да", OperatingCompany="Cofix", SeatsCount=0),
            record(1, "Cofix", *CENTER, IsNetObject="да", OperatingCompany="Cofix", SeatsCount=0),
            record(2, "Кафе без сети", *CENTER, OperatingCompany="ООО Ромашка"),
            record(3, "Без координат", *CENTER, Latitude_WGS84=None),
        ]
    )
    assert frame["poi_id"].tolist() == ["mos_ru:1", "mos_ru:2"]
    assert frame["brand"].tolist() == ["Cofix", None]
    assert frame["seats"].tolist() == [0, 10]


def test_merge_drops_osm_duplicates_within_radius() -> None:
    official = pd.DataFrame([competitor("mos_ru:1", "coffee", CENTER[0], "mos_ru")])
    osm = pd.DataFrame([competitor("n1", "coffee", shifted(40)), competitor("n2", "coffee", shifted(200))])
    merged = mos_ru.merge_competitors(osm, official)
    assert merged["poi_id"].tolist() == ["mos_ru:1", "n2"]


def test_official_points_join_only_niches_with_pattern() -> None:
    city = CityConfig(
        code="moscow",
        name="Москва",
        osm_boundary="mkad",
        scope="inside_mkad",
        h3_resolution=9,
        center=CENTER,
        zoom=11,
    )
    niches = [
        NicheConfig(
            code="coffee",
            name="Кофейня",
            osm_tags=[],
            mos_ru_name_pattern=COFFEE_PATTERN,
            okved=[],
            params_file="",
        ),
        NicheConfig(code="pickup_point", name="Пункт выдачи", osm_tags=[], okved=[], params_file=""),
    ]
    catering = mos_ru.catering_frame(
        [record(1, "Кофейня «Утро»", *CENTER), record(2, "Столовая № 5", shifted(300), CENTER[1])]
    )
    cells = {h3.latlng_to_cell(lat, CENTER[1], 9) for lat in (CENTER[0], shifted(40), shifted(300))}
    official = run.build_mos_ru_competitors(city, niches, catering, cells)
    osm = pd.DataFrame(
        [competitor("n1", "coffee", shifted(40)), competitor("n2", "pickup_point", shifted(40))]
    )
    combined = run.combine_competitors(osm, official)
    assert list(combined.columns) == COMPETITOR_COLUMNS
    assert sorted(combined["poi_id"]) == ["mos_ru:1", "n2"]
    assert combined.loc[combined["poi_id"] == "mos_ru:1", "seats"].tolist() == [10]
