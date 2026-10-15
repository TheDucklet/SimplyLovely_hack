import os
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from geostart.api import data_backend
from geostart.api.main import app
from geostart.model import score_city
from geostart.model.data import configure_environment
from geostart.pipeline.fixtures import build_addresses, write_fixtures
from geostart.storage.connection import DatabaseRole, connect
from geostart.storage.load import load_cities_into_database

configure_environment()
pytestmark = pytest.mark.skipif(
    os.environ.get("GEOSTART_TEST_DATABASE") != "1",
    reason="тесты хранилища запускаются с GEOSTART_TEST_DATABASE=1 и поднятой базой docker compose",
)

client = TestClient(app)


@pytest.fixture(scope="module")
def loaded_city(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("storage")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GEOSTART_DATA_DIR", str(root))
        write_fixtures("tula", root / "processed" / "tula")
        for niche in ("coffee", "pickup_point"):
            score_city("tula", niche)
        load_cities_into_database(["tula"])
    return root


@pytest.fixture
def files_mode(loaded_city: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(loaded_city))
    monkeypatch.setenv("GEOSTART_USE_MOCKS", "false")
    monkeypatch.setenv("GEOSTART_STORAGE", "files")
    data_backend.read_parquet_version.cache_clear()


def test_api_role_cannot_change_data(loaded_city: Path) -> None:
    with connect(DatabaseRole.API) as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
        connection.execute("DELETE FROM geo.scores WHERE city = 'tula'")


def test_reload_replaces_city_rows(loaded_city: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(loaded_city))
    first = load_cities_into_database(["tula"])
    second = load_cities_into_database(["tula"])
    assert first == second
    with connect(DatabaseRole.API) as connection:
        stored = connection.execute("SELECT count(*) FROM geo.hex_features WHERE city = 'tula'").fetchone()[0]
    assert stored == first["tula"]["hex_features"]


def test_database_answers_match_files(files_mode: None, monkeypatch: pytest.MonkeyPatch) -> None:
    requests = [
        ("/api/v1/hexes", {"city": "tula", "niche": "coffee"}),
        ("/api/v1/competitors", {"city": "tula", "niche": "pickup_point"}),
    ]
    from_files = [client.get(path, params=params).json() for path, params in requests]
    monkeypatch.setenv("GEOSTART_STORAGE", "postgres")
    from_database = [client.get(path, params=params).json() for path, params in requests]
    assert from_database[0] == from_files[0]
    assert sorted(item["name"] for item in from_database[1]) == sorted(item["name"] for item in from_files[1])


def test_database_search_puts_exact_house_first(files_mode: None, monkeypatch: pytest.MonkeyPatch) -> None:
    addresses = build_addresses("tula")
    target = addresses[addresses["address"].str.endswith(", 7")]["address"].iloc[0]
    street = target.rsplit(", ", 1)[0]
    monkeypatch.setenv("GEOSTART_STORAGE", "postgres")
    body = client.get("/api/v1/search", params={"city": "tula", "q": f"{street} 7"}).json()
    assert body[0]["address"] == target


def test_unloaded_city_returns_hint(files_mode: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOSTART_STORAGE", "postgres")
    with connect(DatabaseRole.LOADER) as connection:
        connection.execute("DELETE FROM geo.scores WHERE city = 'moscow' AND niche = 'coffee'")
    response = client.get("/api/v1/hexes", params={"city": "moscow", "niche": "coffee"})
    assert response.status_code == 404
    assert "geostart.storage load --city moscow" in response.json()["detail"]
