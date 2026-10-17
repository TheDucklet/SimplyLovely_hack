from datetime import date

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely
from shapely.geometry import Point

from geostart.pipeline import features, geometry, run, trudvsem


def square_wkb(lon: float, lat: float, half_side_degrees: float) -> bytes:
    return shapely.to_wkb(Point(lon, lat).buffer(half_side_degrees, cap_style="square"))


def building_rows(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "building:levels": None,
        "name": None,
        "amenity": None,
        "shop": None,
        "office": None,
        "city": "moscow",
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def test_short_district_name_drops_admin_words() -> None:
    assert run.short_district_name("район Сокол") == "Сокол"
    assert run.short_district_name("Академический район") == "Академический"
    assert run.short_district_name("Центральный территориальный округ") == "Центральный"


def test_cuisine_rule_matches_one_of_several_values() -> None:
    pois = pd.DataFrame(
        {"amenity": ["cafe", "cafe", "restaurant"], "cuisine": ["coffee_shop;bakery", "pizza", None]}
    )
    mask = run.matches_tag_rule(pois, {"amenity": "cafe", "cuisine": "coffee_shop"})
    assert mask.tolist() == [True, False, False]


def test_parse_levels_keeps_plausible_numbers_only() -> None:
    parsed = features.parse_levels(pd.Series(["9", "5;7", "0", "abc", None, "250"]))
    assert parsed.tolist()[:2] == [9.0, 5.0]
    assert parsed.iloc[2:].isna().all()


def test_residential_floor_area_depends_on_building_use() -> None:
    raw = building_rows(
        [
            {
                "osm_id": "w1",
                "building": "apartments",
                "building:levels": "10",
                "wkb": square_wkb(37.6, 55.75, 0.0002),
            },
            {
                "osm_id": "w2",
                "building": "office",
                "building:levels": "10",
                "wkb": square_wkb(37.61, 55.75, 0.0002),
            },
            {
                "osm_id": "w3",
                "building": "yes",
                "building:levels": "10",
                "wkb": square_wkb(37.62, 55.75, 0.0002),
            },
            {"osm_id": "w4", "building": "yes", "wkb": square_wkb(37.63, 55.75, 0.00004)},
        ]
    )
    classified = features.classify_buildings(raw)
    residential = features.residential_floor_area(classified)
    apartments, office, unspecified = residential.iloc[:3]
    assert office == 0
    assert unspecified == pytest.approx(
        apartments * features.UNSPECIFIED_MULTISTOREY_RESIDENTIAL_SHARE, rel=0.05
    )
    assert "w4" not in set(classified["osm_id"]) or residential.iloc[3] == 0


def test_offices_have_workers_and_houses_do_not() -> None:
    raw = building_rows(
        [
            {
                "osm_id": "w1",
                "building": "office",
                "building:levels": "5",
                "wkb": square_wkb(37.6, 55.75, 0.0002),
            },
            {"osm_id": "w2", "building": "house", "wkb": square_wkb(37.61, 55.75, 0.0002)},
        ]
    )
    workers = features.worker_capacity(features.classify_buildings(raw))
    assert workers.iloc[0] > 0
    assert workers.iloc[1] == 0


def test_mkad_polygon_closes_a_ring_of_segments() -> None:
    circle = Point(37.6, 55.75).buffer(0.1).exterior
    coordinates = list(circle.coords)
    halves = [coordinates[: len(coordinates) // 2 + 1], coordinates[len(coordinates) // 2 :]]
    polygon = geometry.mkad_polygon(pd.DataFrame({"coordinates": halves}))
    assert polygon.contains(Point(37.6, 55.75))
    assert polygon.area == pytest.approx(np.pi * 0.1**2, rel=0.05)


def test_vacancy_salary_averages_bounds_and_skips_noise() -> None:
    assert trudvsem.vacancy_salary({"salary_min": 60000, "salary_max": 80000}) == 70000
    assert trudvsem.vacancy_salary({"salary_min": 90000, "salary_max": 0}) == 90000
    assert trudvsem.vacancy_salary({"salary_min": 1000, "salary_max": 0}) is None


def test_old_vacancies_are_ignored() -> None:
    today = date(2026, 10, 14)
    assert trudvsem.is_recent({"creation-date": "2026-05-06"}, today)
    assert not trudvsem.is_recent({"creation-date": "2024-06-02"}, today)


def test_addresses_are_deduplicated_and_kept_inside_cells() -> None:
    from geostart.config import get_city

    city = get_city("moscow")
    inside = run.h3.latlng_to_cell(55.75, 37.6, city.h3_resolution)
    addresses = pd.DataFrame(
        {
            "city": ["moscow", "moscow", "moscow"],
            "street": ["Тверская улица", "Тверская улица", "Тверская улица"],
            "housenumber": ["7", "7", "9"],
            "lon": [37.6, 37.6, 30.3],
            "lat": [55.75, 55.75, 59.9],
        }
    )
    result = run.build_osm_addresses(city, addresses, {inside})
    assert result["address"].tolist() == ["Тверская улица, 7"]


def test_scope_calibration_matches_scope_population() -> None:
    from shapely.geometry import box

    raw = building_rows(
        [
            {
                "osm_id": "w1",
                "building": "apartments",
                "building:levels": "9",
                "wkb": square_wkb(37.60, 55.75, 0.0002),
            },
            {
                "osm_id": "w2",
                "building": "apartments",
                "building:levels": "9",
                "wkb": square_wkb(37.70, 55.75, 0.0002),
            },
        ]
    )
    buildings = features.classify_buildings(raw)
    scope = box(37.55, 55.70, 37.65, 55.80)
    rate = run.residents_per_m2_in(scope, 1000, buildings, "тестовый округ")
    inside_residential = features.residential_floor_area(buildings).iloc[0]
    assert rate * inside_residential == pytest.approx(1000)


def test_district_calibration_matches_each_district_population() -> None:
    from shapely.geometry import box

    raw = building_rows(
        [
            {
                "osm_id": f"w{index}",
                "building": "apartments",
                "building:levels": "9",
                "wkb": square_wkb(lon, 55.75, 0.0002),
            }
            for index, lon in enumerate((37.60, 37.61, 37.70, 37.80))
        ]
    )
    buildings = features.classify_buildings(raw)
    polygons = gpd.GeoDataFrame(
        {"district": ["арбат", "тверской"]},
        geometry=[box(37.55, 55.70, 37.65, 55.80), box(37.66, 55.70, 37.75, 55.80)],
        crs=geometry.GEOGRAPHIC_CRS,
    )
    district = run.buildings_district(buildings, polygons)
    residential = features.residential_floor_area(buildings)
    rates = {
        "арбат": 1000 / residential[district == "арбат"].sum(),
        "тверской": 300 / residential[district == "тверской"].sum(),
    }
    residents = run.residents_by_building(buildings, polygons, rates, fallback_rate=0.01)
    assert residents[district == "арбат"].sum() == pytest.approx(1000)
    assert residents[district == "тверской"].sum() == pytest.approx(300)
    assert residents[district.isna()].sum() == pytest.approx(residential[district.isna()].sum() * 0.01)


def test_district_names_match_regardless_of_admin_words_and_yo() -> None:
    assert run.normalized_district("район Тёплый Стан") == run.normalized_district("Теплый Стан")
    assert run.normalized_district("Пресненский район") == "пресненский"
