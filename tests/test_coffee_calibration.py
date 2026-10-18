import importlib.util
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from geostart import settings
from geostart.pipeline.fixtures import write_fixtures

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/coffee_calibration.py"
SPEC = importlib.util.spec_from_file_location("coffee_calibration", SCRIPT)
calibration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(calibration)


def rcsi_row(**changes) -> dict:
    return {
        "tin": "0123456789",
        "year": "2023",
        "kind": "1",
        "category": "1",
        "org_name": "ООО Тестовая сеть",
        "org_short_name": "Тестовая сеть",
        "activity_code_main": "56.30",
        "region_iso_code": "RU-MOW",
        "region_code": "77",
        "region": "Москва",
        "settlement": "Москва",
        "start_date": "2023-01-01",
        "end_date": "2024-06-10",
        "revenue": "12000000",
    } | changes


def write_rcsi(path: Path, rows: list[dict]) -> Path:
    pd.DataFrame(rows).to_csv(path, sep=";", index=False)
    return path


@pytest.fixture
def spatial_data(tmp_path: Path, monkeypatch) -> tuple[pd.DataFrame, pd.DataFrame]:
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(tmp_path))
    directory = tmp_path / "processed/moscow"
    write_fixtures("moscow", directory)
    addresses = pd.read_parquet(directory / "addresses.parquet").iloc[:2].copy().reset_index(drop=True)
    addresses.loc[0, "address"] = "Тверская улица, 10 к1"
    addresses.loc[1, "address"] = "Тверская улица, 10 к2"
    addresses.to_parquet(directory / "addresses.parquet", index=False)
    points = pd.read_parquet(directory / "competitors.parquet").iloc[:1].copy().reset_index(drop=True)
    points.loc[0, ["lat", "lon", "h3"]] = addresses.loc[0, ["lat", "lon", "h3"]].to_numpy()
    points.loc[0, ["name", "brand", "niche", "source", "poi_id"]] = [
        "Тестовая сеть",
        "Тестовая сеть",
        "coffee",
        "mos_ru",
        "mos_ru:test",
    ]
    points.to_parquet(directory / "competitors.parquet", index=False)
    return addresses, points


def test_streaming_extract_filters_legal_entities_city_and_okved(tmp_path: Path) -> None:
    source = write_rcsi(
        tmp_path / "panel.csv",
        [
            rcsi_row(),
            rcsi_row(tin="1123456789", region_iso_code="RU-TUL", region_code="71", settlement="Тула"),
            rcsi_row(tin="2123456789", region_iso_code="RU-TUL", region_code="71", settlement="Новомосковск"),
            rcsi_row(tin="312345678901", kind="2", org_name="Частное лицо"),
            rcsi_row(tin="4123456789", activity_code_main="56.10"),
        ],
    )
    target = tmp_path / "subset.parquet"
    calibration.extract_rcsi(source, target)
    frame = pd.read_parquet(target)
    assert set(frame.tin) == {"0123456789", "1123456789"}
    assert set(frame.city) == {"moscow", "tula"}
    assert "lat" not in frame and "lon" not in frame


def test_extract_reuses_fingerprint_and_invalidates_on_change(tmp_path: Path, monkeypatch) -> None:
    source = write_rcsi(tmp_path / "panel.csv", [rcsi_row()])
    target = tmp_path / "subset.parquet"
    calibration.extract_rcsi(source, target)

    def rejected(*args, **kwargs):
        pytest.fail("Неизменный исходный CSV не должен сканироваться повторно")

    with monkeypatch.context() as context:
        context.setattr(calibration.duckdb, "connect", rejected)
        assert calibration.extract_rcsi(source, target)["reused"]
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
    assert not calibration.extract_rcsi(source, target).get("reused", False)


def test_periods_do_not_multiply_income_and_conflicts_are_excluded() -> None:
    rows = [
        rcsi_row(),
        rcsi_row(start_date="2023-06-01"),
        rcsi_row(tin="1123456789", revenue="6000000"),
        rcsi_row(tin="1123456789", revenue="7000000", start_date="2023-06-01"),
    ]
    frame, audit = calibration.organization_years(pd.DataFrame(rows).assign(city="moscow"))
    assert len(frame) == 2
    assert audit["duplicates_removed"] == 2
    assert audit["conflicting_revenue_years"] == 1
    assert frame.loc[frame.inn.eq("0123456789"), "revenue_annual_rub"].iloc[0] == 12_000_000
    assert frame.loc[frame.inn.eq("1123456789"), "revenue_annual_rub"].isna().all()


def test_city_change_is_flagged_and_fractional_year_is_not_silently_truncated() -> None:
    raw = pd.DataFrame([rcsi_row(), rcsi_row(), rcsi_row(tin="1123456789", year="2023.5")])
    raw["city"] = ["moscow", "tula", "moscow"]
    frame, audit = calibration.organization_years(raw)
    assert audit["invalid_identifier_or_year"] == 1
    assert audit["multiple_city_years"] == 1
    assert frame.city_year_ambiguous.all()


def test_numeric_amounts_accept_decimal_comma_and_missing_values() -> None:
    amounts = calibration.numeric(pd.Series(["1 234,50", None, "12000.0", "ошибка"]))
    assert amounts.iloc[0] == 1234.5
    assert amounts.iloc[2] == 12000
    assert amounts.iloc[[1, 3]].isna().all()


def test_single_location_is_not_inferred_from_one_record_or_coordinate() -> None:
    raw = pd.DataFrame([rcsi_row()]).assign(city="moscow", lat=55.75, lon=37.61)
    frame, _ = calibration.organization_years(raw)
    frame = calibration.apply_point_counts(frame, None)
    output = calibration.export_columns(frame)
    assert output.h3.isna().all()
    assert not output.single_location_verified.any()
    assert not output.point_calibration_candidate.any()
    assert not calibration.apply_point_counts(
        frame.assign(points_count=1), None
    ).single_location_verified.any()


def test_explicit_point_counts_allow_city_distribution_without_h3(tmp_path: Path) -> None:
    frame, _ = calibration.organization_years(pd.DataFrame([rcsi_row()]).assign(city="moscow"))
    counts = tmp_path / "counts.csv"
    pd.DataFrame(
        [
            {
                "inn": "0123456789",
                "city": "moscow",
                "year": 2023,
                "points_count": 1,
                "points_count_source": "Ручная проверка числа точек за 2023 год",
            }
        ]
    ).to_csv(counts, index=False)
    checked = calibration.apply_point_counts(frame, counts)
    assert checked.single_location_verified.all()
    assert checked.h3.isna().all()
    assert calibration.quantile_row(checked, "moscow", 2023, True)["month_p50"] == 1_000_000


def test_address_and_chain_match_are_local_and_preserve_building(spatial_data) -> None:
    addresses, points = spatial_data
    source = pd.DataFrame(
        [
            {
                "inn": "0123456789",
                "address": "г. Москва, ул. Тверская, д.10, корп.1",
                "name": "ООО Тестовая сеть",
            }
        ]
    )
    linked = calibration.link_girbo(source, addresses, points).iloc[0]
    assert linked.h3 == addresses.iloc[0].h3
    assert linked.address_status == "exact"
    assert linked.mos_ru_poi_id == "mos_ru:test"
    wrong = source.assign(address="Тверская улица, 10 к3")
    assert calibration.link_girbo(wrong, addresses, points).h3.isna().all()


def test_ambiguous_address_does_not_choose_arbitrary_h3(spatial_data) -> None:
    addresses, points = spatial_data
    addresses.loc[1, "address"] = addresses.loc[0, "address"]
    addresses.loc[1, "h3"] = "8911aa7a86bffff"
    source = pd.DataFrame([{"address": "ул. Тверская, 10 корпус 1", "name": "Тестовая сеть"}])
    linked = calibration.link_girbo(source, addresses, points).iloc[0]
    assert linked.address_status == "ambiguous"
    assert pd.isna(linked.h3)
    assert pd.isna(linked.mos_ru_poi_id)


def test_fuzzy_address_and_name_require_clear_margin(spatial_data) -> None:
    addresses, points = spatial_data
    source = pd.DataFrame([{"address": "Тверсая улица, 10 к1", "name": "Тестовая сете"}])
    linked = calibration.link_girbo(source, addresses, points).iloc[0]
    assert linked.address_status == "fuzzy"
    assert linked.chain_status == "fuzzy"
    assert linked.mos_ru_poi_id == "mos_ru:test"


def test_nearby_osm_is_not_used_and_multiple_mos_points_stay_ambiguous(spatial_data) -> None:
    addresses, points = spatial_data
    source = pd.DataFrame([{"address": addresses.iloc[0].address, "name": "Тестовая сеть"}])
    assert calibration.link_girbo(source, addresses, points.assign(source="osm")).mos_ru_poi_id.isna().all()
    duplicate = pd.concat([points, points.assign(poi_id="mos_ru:second")], ignore_index=True)
    linked = calibration.link_girbo(source, addresses, duplicate).iloc[0]
    assert linked.point_ambiguous
    assert pd.isna(linked.mos_ru_poi_id)


def test_girbo_unit_is_explicit_and_inn_keeps_leading_zero(tmp_path: Path) -> None:
    source = tmp_path / "girbo.csv"
    pd.DataFrame(
        [
            {
                "inn": "0123456789",
                "name": "Тестовая сеть",
                "okved": "56.30",
                "address": "ул. А, 1",
                "revenue_2025": "12000",
            }
        ]
    ).to_csv(source, index=False)
    with pytest.raises(ValueError, match="задайте единицу"):
        calibration.read_girbo(source)
    frame = calibration.read_girbo(source, "thousand_rub")
    assert frame.iloc[0].inn == "0123456789"
    assert frame.iloc[0].revenue_annual_rub == 12_000_000
    assert frame.iloc[0].year == 2025


def test_full_export_without_ivan_has_real_background_and_no_fake_single_points(tmp_path: Path) -> None:
    source = write_rcsi(
        tmp_path / "panel.csv",
        [rcsi_row(), rcsi_row(start_date="2023-06-01"), rcsi_row(year="2024", revenue=None)],
    )
    output = tmp_path / "calibration"
    result = calibration.build_calibration(source, tmp_path / "missing.csv", output)
    assert not result["girbo_present"]
    assert result["girbo_coverage"]["address_match_share"] is None
    sample = pd.read_parquet(output / "moscow_coffee.parquet")
    assert len(sample) == 1
    assert sample.iloc[0].year == 2023
    assert sample.h3.isna().all()
    strict = [row for row in result["distributions"] if row["scope"] == "verified_single_location"]
    assert strict[0]["organizations"] == 0
    assert strict[0]["month_p50"] is None
    assert (
        json.loads((output / "rcsi_attribution.json").read_text(encoding="utf-8"))["license"]
        == "CC BY-SA 4.0"
    )


def test_girbo_only_uses_settings_and_keeps_spatial_candidates_separate(tmp_path: Path, spatial_data) -> None:
    addresses, _ = spatial_data
    source = tmp_path / "girbo.csv"
    pd.DataFrame(
        [
            {
                "inn": "0123456789",
                "name": "Тестовая сеть",
                "okved": "56.30",
                "address": addresses.iloc[0].address,
                "revenue_2025_rub": 12_000_000,
                "points_count": 1,
                "points_count_source": "Ручная проверка за 2025 год",
            }
        ]
    ).to_csv(source, index=False)
    output = settings.data_dir() / "calibration"
    result = calibration.build_calibration(None, source, output)
    assert result["girbo_coverage"]["address_match_share"] == 1
    sample = pd.read_parquet(output / "moscow_coffee.parquet")
    assert sample.point_calibration_candidate.all()
    assert sample.iloc[0].revenue_metric == "sales_revenue"


def test_missing_inputs_stop_without_creating_empirical_sample(tmp_path: Path) -> None:
    output = tmp_path / "output"
    with pytest.raises(FileNotFoundError, match="Нет ни локального"):
        calibration.build_calibration(None, tmp_path / "missing.csv", output)
    assert not output.exists()
