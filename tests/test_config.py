import pytest

from geostart.config import UnknownCityError, UnknownNicheError, get_city, get_niche, load_cities, load_niches


def test_cities_from_config_list_six_cities() -> None:
    assert [city.code for city in load_cities()] == [
        "moscow",
        "tula",
        "yaroslavl",
        "saint_petersburg",
        "novosibirsk",
        "yekaterinburg",
    ]


def test_niches_from_config_list_eight_niches() -> None:
    assert [niche.code for niche in load_niches()] == [
        "coffee",
        "pickup_point",
        "pickup_point_multi",
        "grocery",
        "beauty_salon",
        "fast_food",
        "bakery",
        "flowers",
    ]
    assert {niche.code: niche.demand_kind for niche in load_niches()}["pickup_point"] == "orders"


def test_niche_params_files_exist() -> None:
    from geostart.settings import REPOSITORY_ROOT

    for niche in load_niches():
        assert (REPOSITORY_ROOT / niche.params_file).is_file()


def test_unknown_city_error_lists_available_cities() -> None:
    with pytest.raises(
        UnknownCityError,
        match="доступны: moscow, tula, yaroslavl, saint_petersburg, novosibirsk, yekaterinburg",
    ):
        get_city("kazan")


def test_unknown_niche_error_lists_available_niches() -> None:
    with pytest.raises(UnknownNicheError, match="доступны: coffee, pickup_point"):
        get_niche("dentistry")
