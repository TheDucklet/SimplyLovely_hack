import h3
import pandas as pd
import pytest

from geostart.pipeline.fixtures import (
    ADDRESS_COLUMNS,
    COMPETITOR_COLUMNS,
    HEX_FEATURE_COLUMNS,
    WAGE_COLUMNS,
    build_competitors,
    build_hex_features,
    write_fixtures,
)

INTEGER_FEATURES = ["offices_n", "education_n", "malls_n", "transit_stops_n"]
FLOAT_FEATURES = ["lat", "lon", "residents", "workers", "metro_dist_m"]


@pytest.mark.parametrize("city_code", ["moscow", "tula"])
def test_written_files_follow_contract_columns(city_code: str, tmp_path) -> None:
    target = write_fixtures(city_code, tmp_path)
    expected = {
        "hex_features.parquet": HEX_FEATURE_COLUMNS,
        "competitors.parquet": COMPETITOR_COLUMNS,
        "wages.parquet": WAGE_COLUMNS,
        "addresses.parquet": ADDRESS_COLUMNS,
    }
    for file_name, columns in expected.items():
        assert list(pd.read_parquet(target / file_name).columns) == columns


def test_hex_feature_types_follow_contract() -> None:
    features = build_hex_features("moscow")
    for column in INTEGER_FEATURES:
        assert pd.api.types.is_integer_dtype(features[column])
    for column in FLOAT_FEATURES:
        assert pd.api.types.is_float_dtype(features[column])
    assert features["h3"].map(h3.get_resolution).eq(9).all()
    assert features["h3"].is_unique


def test_fixtures_are_reproducible() -> None:
    build_hex_features.cache_clear()
    first = build_hex_features("tula").copy()
    build_hex_features.cache_clear()
    second = build_hex_features("tula")
    pd.testing.assert_frame_equal(first, second)


def test_tula_has_no_metro_distances() -> None:
    assert build_hex_features("tula")["metro_dist_m"].isna().all()
    assert build_hex_features("moscow")["metro_dist_m"].notna().all()


def test_competitor_cells_match_coordinates() -> None:
    competitors = build_competitors("moscow")
    recomputed = [h3.latlng_to_cell(row.lat, row.lon, 9) for row in competitors.itertuples(index=False)]
    assert competitors["h3"].tolist() == recomputed
    assert set(competitors["source"]) <= {"osm", "mos_ru"}
    assert competitors.loc[competitors["source"] == "osm", "seats"].isna().all()
