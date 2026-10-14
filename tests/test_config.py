import pytest

from geostart.config import UnknownCityError, UnknownNicheError, get_city, get_niche, load_cities, load_niches


def test_cities_from_config_are_moscow_and_tula() -> None:
    assert [city.code for city in load_cities()] == ["moscow", "tula"]


def test_niches_from_config_are_coffee_and_pickup_point() -> None:
    assert [niche.code for niche in load_niches()] == ["coffee", "pickup_point"]


def test_niche_params_files_exist() -> None:
    from geostart.settings import REPOSITORY_ROOT

    for niche in load_niches():
        assert (REPOSITORY_ROOT / niche.params_file).is_file()


def test_unknown_city_error_lists_available_cities() -> None:
    with pytest.raises(UnknownCityError, match="доступны: moscow, tula"):
        get_city("kazan")


def test_unknown_niche_error_lists_available_niches() -> None:
    with pytest.raises(UnknownNicheError, match="доступны: coffee, pickup_point"):
        get_niche("bakery")
