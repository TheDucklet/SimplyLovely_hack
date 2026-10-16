import yaml

from geostart.research import city_parameters
from geostart.settings import research_dir

RAW = {
    "niche": "coffee",
    "demand": {
        "avg_check_rub": {"p50": 320},
        "avg_check_rub_moscow": {"p50": 380},
        "avg_check_rub_tula": {"p50": 280},
        "visits_per_resident_month": {"p50": 2.2},
    },
    "costs": {"other_opex_rub": {"p50": 65000}, "other_opex_rub_tula": {"p50": 45000}},
    "capex_rub": {"p50": 2800000},
    "capex_rub_moscow": {"p50": 3200000},
    "benchmarks": {"revenue_rub_month_moscow": {"p50": 1100000}, "revenue_rub_month_tula": {"p50": 650000}},
}


def test_city_values_override_base_and_suffixes_disappear() -> None:
    moscow = city_parameters(RAW, "moscow")
    assert moscow["demand"]["avg_check_rub"]["p50"] == 380
    assert moscow["costs"]["other_opex_rub"]["p50"] == 65000
    assert moscow["capex_rub"]["p50"] == 3200000
    assert moscow["benchmarks"] == {"revenue_rub_month": {"p50": 1100000}}
    assert not any(key.endswith(("_moscow", "_tula")) for key in moscow["demand"])


def test_base_value_is_kept_when_city_has_no_override() -> None:
    tula = city_parameters(RAW, "tula")
    assert tula["demand"]["avg_check_rub"]["p50"] == 280
    assert tula["costs"]["other_opex_rub"]["p50"] == 45000
    assert tula["capex_rub"]["p50"] == 2800000
    assert tula["demand"]["visits_per_resident_month"]["p50"] == 2.2


def test_research_files_resolve_for_every_city() -> None:
    for niche in ("coffee", "pickup_point"):
        raw = yaml.safe_load((research_dir() / "niche_params" / f"{niche}.yaml").read_text(encoding="utf-8"))
        for city in ("moscow", "tula"):
            parameters = city_parameters(raw, city)
            assert "outside_option_weight" in parameters["demand"]
            assert "revenue_rub_month" in parameters["benchmarks"]
