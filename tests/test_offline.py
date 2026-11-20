import importlib.util
import ipaddress
import json
import re
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geostart.api import data_backend
from geostart.api.main import app
from geostart.config import get_city
from geostart.model import score_city
from geostart.pipeline.fixtures import write_fixtures

ROOT = Path(__file__).resolve().parents[1]
BASEMAP = ROOT / "docker" / "web" / "basemap"
NGINX_CONFIGS = [ROOT / "docker" / "web" / "nginx.conf", ROOT / "docker" / "web" / "nginx.vps.conf"]
INTERNAL_UPSTREAMS = {"http://api:8000", "http://tiles:8080/"}
REQUIRED_GLYPH_RANGES = ["0-255.pbf", "1024-1279.pbf", "8192-8447.pbf"]
client = TestClient(app)


@pytest.fixture(scope="module")
def data_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("data")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GEOSTART_DATA_DIR", str(root))
        write_fixtures("tula", root / "processed" / "tula")
        score_city("tula", "coffee")
    return root


@pytest.fixture
def external_calls(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(data_root))
    monkeypatch.setenv("GEOSTART_USE_MOCKS", "false")
    data_backend.read_parquet_version.cache_clear()
    calls: list[str] = []
    original_connect = socket.socket.connect
    original_getaddrinfo = socket.getaddrinfo

    def is_local(host: object) -> bool:
        if host in ("localhost", None):
            return True
        try:
            return ipaddress.ip_address(str(host)).is_loopback
        except ValueError:
            return False

    def guarded_connect(self: socket.socket, address: object) -> None:
        host = address[0] if isinstance(address, tuple) else None
        if self.family in (socket.AF_INET, socket.AF_INET6) and not is_local(host):
            calls.append(f"connect {host}")
            raise ConnectionRefusedError(f"внешнее соединение с {host} запрещено")
        return original_connect(self, address)

    def guarded_getaddrinfo(host: object, *args: object, **kwargs: object) -> list:
        if not is_local(host):
            calls.append(f"dns {host}")
            raise socket.gaierror(f"разрешение имени {host} запрещено")
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    return calls


def test_api_works_without_external_network(external_calls: list[str]) -> None:
    center = get_city("tula").center
    point = {"lat": center[0], "lon": center[1]}
    responses = [
        client.get("/api/v1/health"),
        client.get("/api/v1/cities"),
        client.get("/api/v1/niches"),
        client.get("/api/v1/hexes", params={"city": "tula", "niche": "coffee"}),
        client.get("/api/v1/competitors", params={"city": "tula", "niche": "coffee"}),
        client.get("/api/v1/search", params={"city": "tula", "q": "Тестовая"}),
        client.post("/api/v1/report", json={"city": "tula", "niche": "coffee", **point, "area_m2": 40}),
        client.post(
            "/api/v2/economics",
            json={"city": "tula", "niche": "coffee", "demand": {"source": "geostart", **point}},
        ),
        client.get("/api/v2/norms/coffee", params={"city": "tula"}),
        client.get("/api/v2/credit-products"),
    ]
    assert [response.status_code for response in responses] == [200] * len(responses)
    assert external_calls == []


def test_guard_catches_external_connection(external_calls: list[str]) -> None:
    with pytest.raises(OSError):
        socket.create_connection(("example.com", 443), timeout=1)
    assert external_calls == ["dns example.com"]


def load_style_script():
    spec = importlib.util.spec_from_file_location("basemap_style", ROOT / "scripts" / "basemap_style.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_basemap_style_is_generated_and_local() -> None:
    script = load_style_script()
    text = script.STYLE_PATH.read_text(encoding="utf-8")
    style = json.loads(text)
    assert style == script.build_style()
    assert "http" not in text
    assert all(url.startswith("/basemap/") for url in style["sources"]["protomaps"]["tiles"])
    assert style["glyphs"].startswith("/basemap/fonts/")


def test_basemap_fonts_cover_cyrillic() -> None:
    style = json.loads((BASEMAP / "style.json").read_text(encoding="utf-8"))
    fonts = {font for layer in style["layers"] for font in layer.get("layout", {}).get("text-font", [])}
    assert fonts
    for font in fonts:
        for glyph_range in REQUIRED_GLYPH_RANGES:
            assert (BASEMAP / "fonts" / font / glyph_range).stat().st_size > 0
    assert (BASEMAP / "fonts" / "empty.pbf").exists()


@pytest.mark.parametrize("config", NGINX_CONFIGS, ids=lambda path: path.name)
def test_nginx_proxies_only_internal_services(config: Path) -> None:
    text = config.read_text(encoding="utf-8")
    assert set(re.findall(r"proxy_pass\s+([^;]+);", text)) == INTERNAL_UPSTREAMS
    assert "location /basemap/tiles/" in text


def test_web_build_uses_local_basemap() -> None:
    dockerfile = (ROOT / "docker" / "web" / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "compose.demo.yml").read_text(encoding="utf-8")
    assert "ARG VITE_MAP_STYLE_URL=/basemap/style.json" in dockerfile
    assert "COPY docker/web/basemap /usr/share/nginx/html/basemap" in dockerfile
    assert "${GEOSTART_MAP_STYLE_URL:-/basemap/style.json}" in compose
    for name in ("compose.demo.yml", "compose.vps.yml"):
        assert "protomaps/go-pmtiles:v1.31.2" in (ROOT / name).read_text(encoding="utf-8")


def test_web_index_loads_no_external_assets() -> None:
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"""(src|href)=["']https?://""", index)
