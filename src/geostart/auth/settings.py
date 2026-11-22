import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from geostart.settings import TRUE_VALUES, data_dir

AUTH_MODES = {"off", "oidc"}
MIN_SECRET_LENGTH = 32
CALLBACK_PATH = "/api/auth/callback"
STUB_PATH = "/idp"
STUB_INTERNAL_URL = "http://127.0.0.1:8000/idp"


class AuthConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AuthSettings:
    mode: str
    public_url: str
    issuer: str
    internal_url: str
    client_id: str
    client_secret: str
    audience: str
    roles_claim: str
    role_map: dict[str, str]
    session_secret: str
    session_hours: float
    cookie_secure: bool
    stub: bool

    @property
    def enabled(self) -> bool:
        return self.mode == "oidc"

    @property
    def redirect_uri(self) -> str:
        return self.public_url + CALLBACK_PATH


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def stub_enabled() -> bool:
    return env("GEOSTART_IDP_STUB", "false").lower() in TRUE_VALUES


def secrets_dir() -> Path:
    return data_dir() / "auth"


def stored_secret(name: str) -> str:
    path = secrets_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(48))
    except FileExistsError:
        pass
    return path.read_text(encoding="utf-8").strip()


def secret(name: str, stub: bool) -> str:
    value = env(name)
    if not value and stub:
        value = stored_secret(name.lower())
    return value


def parse_role_map(raw: str) -> dict[str, str]:
    pairs = [item.split("=", 1) for item in raw.split(",") if "=" in item]
    return {external.strip(): role.strip() for external, role in pairs if external.strip() and role.strip()}


def auth_settings() -> AuthSettings:
    mode = env("GEOSTART_AUTH_MODE", "off").lower()
    if mode not in AUTH_MODES:
        raise AuthConfigError(f"GEOSTART_AUTH_MODE должен быть off или oidc, получено {mode}")
    stub = stub_enabled()
    public_url = env("GEOSTART_PUBLIC_URL").rstrip("/")
    client_id = env("GEOSTART_OIDC_CLIENT_ID", "geostart")
    issuer = env("GEOSTART_OIDC_ISSUER").rstrip("/") or (
        public_url + STUB_PATH if stub and public_url else ""
    )
    internal_url = env("GEOSTART_OIDC_INTERNAL_URL").rstrip("/")
    if stub and not internal_url and issuer == public_url + STUB_PATH:
        internal_url = STUB_INTERNAL_URL
    settings = AuthSettings(
        mode=mode,
        public_url=public_url,
        issuer=issuer,
        internal_url=internal_url,
        client_id=client_id,
        client_secret=secret("GEOSTART_OIDC_CLIENT_SECRET", stub) if mode == "oidc" or stub else "",
        audience=env("GEOSTART_OIDC_AUDIENCE", client_id),
        roles_claim=env("GEOSTART_OIDC_ROLES_CLAIM", "roles"),
        role_map=parse_role_map(env("GEOSTART_OIDC_ROLE_MAP")),
        session_secret=secret("GEOSTART_SESSION_SECRET", stub) if mode == "oidc" else "",
        session_hours=float(env("GEOSTART_SESSION_HOURS", "8")),
        cookie_secure=urlsplit(public_url).scheme == "https",
        stub=stub,
    )
    if settings.enabled:
        validate(settings)
    return settings


def validate(settings: AuthSettings) -> None:
    missing = [
        name
        for name, value in [
            ("GEOSTART_PUBLIC_URL", settings.public_url),
            ("GEOSTART_OIDC_ISSUER", settings.issuer),
            ("GEOSTART_OIDC_CLIENT_SECRET", settings.client_secret),
            ("GEOSTART_SESSION_SECRET", settings.session_secret),
        ]
        if not value
    ]
    if missing:
        raise AuthConfigError(f"Для входа через OIDC задайте в .env {', '.join(missing)}")
    if len(settings.session_secret) < MIN_SECRET_LENGTH:
        raise AuthConfigError(f"GEOSTART_SESSION_SECRET короче {MIN_SECRET_LENGTH} символов")
    if urlsplit(settings.public_url).scheme not in {"http", "https"}:
        raise AuthConfigError("GEOSTART_PUBLIC_URL должен начинаться с http:// или https://")
