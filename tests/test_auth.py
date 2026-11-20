import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from geostart.api.main import app
from geostart.auth import oidc
from geostart.auth.roles import ROLE_PERMISSIONS, Permission, Role
from geostart.auth.settings import AuthConfigError, AuthSettings, auth_settings
from geostart.auth.tokens import SESSION_COOKIE, pkce_pair
from geostart.config import get_city

PUBLIC_URL = "http://testserver"
ISSUER = f"{PUBLIC_URL}/idp"
HIDDEN = re.compile(r'<input type="hidden" name="([^"]+)" value="([^"]*)">')


@pytest.fixture
def oidc_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GEOSTART_AUTH_MODE", "oidc")
    monkeypatch.setenv("GEOSTART_IDP_STUB", "true")
    monkeypatch.setenv("GEOSTART_PUBLIC_URL", PUBLIC_URL)
    monkeypatch.setenv("GEOSTART_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("GEOSTART_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GEOSTART_AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setenv("GEOSTART_USE_MOCKS", "true")
    for name in ("GEOSTART_OIDC_CLIENT_SECRET", "GEOSTART_SESSION_SECRET", "GEOSTART_OIDC_INTERNAL_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(oidc, "http_client", lambda: TestClient(app))
    oidc.reset_cache()
    yield tmp_path
    oidc.reset_cache()


def stub_form(client: TestClient, authorize_url: str) -> dict[str, str]:
    page = client.get(authorize_url)
    assert page.status_code == 200
    return dict(HIDDEN.findall(page.text.split("</form>")[0]))


def login(client: TestClient, subject: str, next_path: str = "/") -> str:
    start = client.get("/api/auth/login", params={"next": next_path}, follow_redirects=False)
    assert start.status_code == 303
    assert start.headers["location"].startswith(f"{ISSUER}/authorize?")
    fields = {**stub_form(client, start.headers["location"]), "sub": subject}
    chosen = client.post("/idp/authorize", data=fields, follow_redirects=False)
    assert chosen.status_code == 303
    assert chosen.headers["location"].startswith(f"{PUBLIC_URL}/api/auth/callback?")
    finish = client.get(chosen.headers["location"], follow_redirects=False)
    assert finish.status_code == 303, finish.text
    return finish.headers["location"]


def stub_tokens(client: TestClient, subject: str) -> dict:
    verifier, challenge = pkce_pair()
    settings = auth_settings()
    fields = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "state": "s",
        "nonce": "n",
        "code_challenge": challenge,
        "sub": subject,
    }
    chosen = client.post("/idp/authorize", data=fields, follow_redirects=False)
    code = parse_qs(urlsplit(chosen.headers["location"]).query)["code"][0]
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.redirect_uri,
        "code_verifier": verifier,
    }
    response = client.post("/idp/token", data=form, auth=(settings.client_id, settings.client_secret))
    assert response.status_code == 200, response.text
    return {**response.json(), "form": form}


def report_body() -> dict:
    lat, lon = get_city("moscow").center
    return {"city": "moscow", "niche": "coffee", "lat": lat, "lon": lon, "area_m2": 40}


def test_api_requires_login(oidc_env: Path) -> None:
    client = TestClient(app)
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/cities").status_code == 401
    denied = client.get("/api/v2/credit-products")
    assert denied.status_code == 401
    assert denied.headers["content-type"].startswith("application/problem+json")


def test_login_through_stub_creates_session(oidc_env: Path) -> None:
    client = TestClient(app)
    assert login(client, "demo-credit-officer", "/#map") == "/#map"
    cookie = next(item for item in client.cookies.jar if item.name == SESSION_COOKIE)
    assert cookie.has_nonstandard_attr("HttpOnly")
    me = client.get("/api/auth/me").json()
    assert me["mode"] == "oidc"
    assert me["name"] == "Кредитный специалист"
    assert me["roles"] == ["credit_officer"]
    assert "credit_check" in me["permissions"]
    assert client.get("/api/v1/cities").status_code == 200


@pytest.mark.parametrize(
    ("subject", "method", "path", "expected"),
    [
        ("demo-entrepreneur", "POST", "/api/v2/credit-check", 403),
        ("demo-credit-officer", "POST", "/api/v2/credit-check", 422),
        ("demo-analyst", "POST", "/api/v2/credit-check", 403),
        ("demo-admin", "POST", "/api/v2/credit-check", 403),
        ("demo-entrepreneur", "GET", "/api/admin/access-stats", 403),
        ("demo-analyst", "GET", "/api/admin/access-stats", 200),
        ("demo-analyst", "GET", "/api/admin/access-log", 403),
        ("demo-admin", "GET", "/api/admin/access-log", 200),
        ("demo-credit-officer", "GET", "/api/admin/access-log", 403),
    ],
)
def test_role_matrix(oidc_env: Path, subject: str, method: str, path: str, expected: int) -> None:
    client = TestClient(app)
    login(client, subject)
    response = client.request(method, path, json={} if method == "POST" else None)
    assert response.status_code == expected


def test_every_role_gets_location_report(oidc_env: Path) -> None:
    for role in Role:
        assert {Permission.VIEW_MAP, Permission.LOCATION_REPORT} <= ROLE_PERMISSIONS[role]
    client = TestClient(app)
    login(client, "demo-entrepreneur")
    assert client.post("/api/v1/report", json=report_body()).status_code == 200


def test_access_log_has_pseudonyms_and_no_coordinates(oidc_env: Path) -> None:
    anonymous = TestClient(app)
    assert anonymous.post("/api/v1/report", json=report_body()).status_code == 401
    client = TestClient(app)
    login(client, "demo-admin")
    assert client.post("/api/v1/report", json=report_body()).status_code == 200
    text = "".join(path.read_text(encoding="utf-8") for path in (oidc_env / "audit").glob("*.jsonl"))
    lat, lon = get_city("moscow").center
    for forbidden in ("lat", "lon", str(lat)[:6], str(lon)[:6], "demo-admin", "area_m2"):
        assert forbidden not in text
    entries = client.get("/api/admin/access-log").json()
    assert [(entry["action"], entry["status"]) for entry in entries] == [
        ("location_report", 200),
        ("location_report", 401),
    ]
    latest, rejected = entries
    assert (latest["city"], latest["niche"], latest["roles"]) == ("moscow", "coffee", ["admin"])
    assert re.fullmatch(r"[0-9a-f]{16}", latest["user"])
    assert rejected["user"] is None
    stats = client.get("/api/admin/access-stats").json()
    assert {(item["outcome"], item["count"]) for item in stats} == {("ok", 1), ("denied", 1)}


def test_access_log_ignores_unknown_place_values(oidc_env: Path) -> None:
    client = TestClient(app)
    login(client, "demo-admin")
    client.post("/api/v1/report", json={**report_body(), "city": "55.75,37.61"})
    entry = client.get("/api/admin/access-log").json()[0]
    assert entry["city"] == "unknown"


def test_bearer_token_from_bank_server(oidc_env: Path) -> None:
    client = TestClient(app)
    tokens = stub_tokens(client, "demo-analyst")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get("/api/v1/cities", headers=headers).status_code == 200
    assert client.get("/api/admin/access-stats", headers=headers).status_code == 200
    assert client.get("/api/admin/access-log", headers=headers).status_code == 403
    assert client.get("/api/v1/cities", headers={"Authorization": "Bearer broken"}).status_code == 401
    userinfo = client.get("/idp/userinfo", headers=headers).json()
    assert userinfo == {"sub": "demo-analyst", "name": "Аналитик", "roles": ["analyst"]}


def test_stub_rejects_reused_code_and_wrong_verifier(oidc_env: Path) -> None:
    client = TestClient(app)
    tokens = stub_tokens(client, "demo-entrepreneur")
    settings = auth_settings()
    credentials = (settings.client_id, settings.client_secret)
    reused = client.post("/idp/token", data=tokens["form"], auth=credentials)
    assert reused.json()["error"] == "invalid_grant"
    fresh = stub_tokens(client, "demo-entrepreneur")["form"]
    wrong = client.post("/idp/token", data={**fresh, "code_verifier": "x" * 50}, auth=credentials)
    assert wrong.status_code == 400
    bad_client = client.post("/idp/token", data=fresh, auth=(settings.client_id, "wrong"))
    assert bad_client.status_code == 401


def test_callback_rejects_foreign_state(oidc_env: Path) -> None:
    client = TestClient(app)
    start = client.get("/api/auth/login", follow_redirects=False)
    fields = {**stub_form(client, start.headers["location"]), "sub": "demo-admin", "state": "foreign"}
    chosen = client.post("/idp/authorize", data=fields, follow_redirects=False)
    assert client.get(chosen.headers["location"], follow_redirects=False).status_code == 401
    assert client.get("/api/v1/cities").status_code == 401


def test_forged_session_cookie_is_rejected(oidc_env: Path) -> None:
    client = TestClient(app, cookies={SESSION_COOKIE: "eyJhbGciOiJub25lIn0.e30."})
    assert client.get("/api/v1/cities").status_code == 401


@pytest.mark.parametrize("target", ["//evil.example/", "https://evil.example/", "/\\evil.example"])
def test_login_does_not_redirect_outside(oidc_env: Path, target: str) -> None:
    client = TestClient(app)
    assert login(client, "demo-entrepreneur", target) == "/"


def test_login_moves_to_public_host_first(oidc_env: Path) -> None:
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.get("/api/auth/login", params={"next": "/x"}, follow_redirects=False)
    assert response.headers["location"] == f"{PUBLIC_URL}/api/auth/login?next=%2Fx&relay=true"


def test_logout_clears_session_and_returns_through_stub(oidc_env: Path) -> None:
    client = TestClient(app)
    login(client, "demo-entrepreneur")
    response = client.get("/api/auth/logout", follow_redirects=False)
    assert response.headers["location"].startswith(f"{ISSUER}/logout?")
    assert client.get("/api/v1/cities").status_code == 401


def test_stub_is_hidden_when_disabled(oidc_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOSTART_IDP_STUB", "false")
    monkeypatch.setenv("GEOSTART_OIDC_CLIENT_SECRET", "s" * 40)
    monkeypatch.setenv("GEOSTART_SESSION_SECRET", "t" * 40)
    assert TestClient(app).get("/idp/.well-known/openid-configuration").status_code == 404


def test_off_mode_keeps_api_open(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GEOSTART_AUTH_MODE", "off")
    monkeypatch.setenv("GEOSTART_USE_MOCKS", "true")
    monkeypatch.setenv("GEOSTART_AUDIT_DIR", str(tmp_path))
    client = TestClient(app)
    assert client.get("/api/auth/me").json()["mode"] == "off"
    assert client.post("/api/v1/report", json=report_body()).status_code == 200
    assert not list(tmp_path.iterdir())


def test_oidc_mode_requires_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOSTART_AUTH_MODE", "oidc")
    monkeypatch.setenv("GEOSTART_IDP_STUB", "false")
    for name in ("GEOSTART_PUBLIC_URL", "GEOSTART_OIDC_ISSUER", "GEOSTART_SESSION_SECRET"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(AuthConfigError, match="GEOSTART_OIDC_ISSUER"):
        auth_settings()


def test_roles_from_bank_claims() -> None:
    settings = AuthSettings(
        mode="oidc",
        public_url=PUBLIC_URL,
        issuer=ISSUER,
        internal_url="",
        client_id="geostart",
        client_secret="",
        audience="geostart",
        roles_claim="realm_access.roles",
        role_map={"SME_CREDIT": "credit_officer"},
        session_secret="",
        session_hours=8,
        cookie_secure=False,
        stub=False,
    )
    claims = {"realm_access": {"roles": ["SME_CREDIT", "admin", "offline_access"]}}
    assert oidc.roles_from_claims(settings, claims) == {Role.CREDIT_OFFICER, Role.ADMIN}
    assert oidc.roles_from_claims(settings, {"realm_access": "x"}) == frozenset()
    assert json.loads(json.dumps(sorted(ROLE_PERMISSIONS[Role.ADMIN]))) == sorted(
        {"view_map", "location_report", "access_stats", "access_log"}
    )
