import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

import jwt
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from geostart.auth.settings import AuthSettings, auth_settings, secrets_dir
from geostart.auth.tokens import pkce_challenge
from geostart.settings import config_dir

KEY_FILE = "idp_stub_key.pem"
CODE_AUDIENCE = "geostart-stub-code"
CODE_LIFETIME = timedelta(minutes=2)
ID_TOKEN_LIFETIME = timedelta(minutes=5)
ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
AUTHORIZE_FIELDS = ("client_id", "redirect_uri", "state", "nonce", "code_challenge")

PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Вход в ГеоСтарт</title>
<style>
body {{ margin: 0; font-family: system-ui, sans-serif; background: #f2f5fa; color: #0a2e73; }}
main {{ max-width: 520px; margin: 48px auto; padding: 0 16px; }}
h1 {{ font-size: 24px; margin: 0 0 8px; }}
p.lead {{ margin: 0 0 24px; color: #4a5b7a; line-height: 1.45; }}
form {{ margin: 0 0 12px; }}
button {{ width: 100%; text-align: left; padding: 14px 16px; border: 1px solid #c9d5e8;
  border-radius: 10px; background: #fff; color: inherit; font: inherit; cursor: pointer; }}
button:hover, button:focus-visible {{ border-color: #0077c8; outline: none; }}
button strong {{ display: block; font-size: 16px; }}
button span {{ display: block; margin-top: 4px; font-size: 13px; color: #4a5b7a; }}
</style>
</head>
<body>
<main>
<h1>Вход в ГеоСтарт</h1>
<p class="lead">Заглушка единого входа банка для стенда.
В контуре банка вместо неё работает сервер входа банка,
а ГеоСтарт получает от него только идентификатор и роли.</p>
{forms}
</main>
</body>
</html>
"""


@dataclass(frozen=True)
class StubUser:
    sub: str
    name: str
    roles: list[str]
    note: str


@lru_cache
def users() -> dict[str, StubUser]:
    raw = yaml.safe_load((config_dir() / "auth_stub_users.yaml").read_text(encoding="utf-8"))
    return {item["sub"]: StubUser(**item) for item in raw["users"]}


def private_key_path() -> Path:
    return secrets_dir() / KEY_FILE


def private_key() -> rsa.RSAPrivateKey:
    path = private_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        generated = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = generated.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        try:
            with open(path, "xb") as stream:
                stream.write(pem)
        except FileExistsError:
            pass
    return load_key(path, path.stat().st_mtime_ns)


@lru_cache(maxsize=2)
def load_key(path: Path, _modified: int) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError(f"В {path} не ключ RSA")
    return key


def key_id(key: rsa.RSAPrivateKey) -> str:
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.urlsafe_b64encode(hashlib.sha256(der).digest()[:12]).rstrip(b"=").decode()


def settings_or_404() -> AuthSettings:
    settings = auth_settings()
    if not settings.stub or not settings.issuer or not settings.client_secret:
        raise HTTPException(status_code=404, detail="Заглушка входа выключена")
    return settings


def check_client(settings: AuthSettings, client_id: str, redirect_uri: str) -> None:
    if client_id != settings.client_id or redirect_uri != settings.redirect_uri:
        raise HTTPException(status_code=400, detail="Неизвестный клиент или адрес возврата")


def oauth_error(code: str, description: str) -> JSONResponse:
    return JSONResponse({"error": code, "error_description": description}, status_code=400, headers=NO_STORE)


async def form(request: Request) -> dict[str, str]:
    return dict(parse_qsl((await request.body()).decode("utf-8")))


def client_credentials(request: Request, fields: dict[str, str]) -> tuple[str, str]:
    scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "basic" and encoded:
        client_id, _, client_secret = base64.b64decode(encoded).decode().partition(":")
        return client_id, client_secret
    return fields.get("client_id", ""), fields.get("client_secret", "")


def signed(claims: dict, lifetime: timedelta) -> str:
    key = private_key()
    now = datetime.now(UTC)
    return jwt.encode(
        {**claims, "iat": now, "exp": now + lifetime}, key, algorithm="RS256", headers={"kid": key_id(key)}
    )


app = FastAPI(title="Заглушка единого входа", docs_url=None, redoc_url=None, openapi_url=None)
used_codes: set[str] = set()


@app.get("/.well-known/openid-configuration")
def discovery() -> dict:
    issuer = settings_or_404().issuer
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "jwks_uri": f"{issuer}/jwks",
        "userinfo_endpoint": f"{issuer}/userinfo",
        "end_session_endpoint": f"{issuer}/logout",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["openid", "profile"],
        "claims_supported": ["sub", "name", "roles"],
    }


@app.get("/jwks")
def jwks() -> dict:
    settings_or_404()
    key = private_key()
    public = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {"keys": [{**public, "kid": key_id(key), "use": "sig", "alg": "RS256"}]}


@app.get("/authorize", response_class=HTMLResponse)
def authorize_page(
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    response_type: str = "code",
    code_challenge_method: str = "S256",
    nonce: str = "",
    scope: str = "openid",
) -> HTMLResponse:
    settings = settings_or_404()
    check_client(settings, client_id, redirect_uri)
    if response_type != "code" or code_challenge_method != "S256" or "openid" not in scope.split():
        raise HTTPException(status_code=400, detail="Поддерживается только code с PKCE S256 и scope openid")
    request_fields = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
    }
    hidden = "".join(
        f'<input type="hidden" name="{name}" value="{escape(value)}">'
        for name, value in request_fields.items()
    )
    forms = "\n".join(
        f'<form method="post" action="authorize">{hidden}'
        f'<input type="hidden" name="sub" value="{escape(user.sub)}">'
        f"<button><strong>{escape(user.name)}</strong><span>{escape(user.note)}</span></button></form>"
        for user in users().values()
    )
    return HTMLResponse(PAGE.format(forms=forms), headers=NO_STORE)


@app.post("/authorize")
async def authorize(request: Request) -> RedirectResponse:
    settings = settings_or_404()
    fields = await form(request)
    check_client(settings, fields.get("client_id", ""), fields.get("redirect_uri", ""))
    if fields.get("sub") not in users() or not fields.get("code_challenge"):
        raise HTTPException(status_code=400, detail="Неизвестный пользователь заглушки")
    payload = {name: fields.get(name, "") for name in (*AUTHORIZE_FIELDS, "sub")}
    now = datetime.now(UTC)
    code = jwt.encode(
        {**payload, "jti": secrets.token_urlsafe(12), "aud": CODE_AUDIENCE, "exp": now + CODE_LIFETIME},
        settings.client_secret,
        algorithm="HS256",
    )
    query = urlencode({"code": code, "state": fields.get("state", "")})
    return RedirectResponse(f"{fields['redirect_uri']}?{query}", status_code=303, headers=NO_STORE)


@app.post("/token")
async def token(request: Request) -> JSONResponse:
    settings = settings_or_404()
    fields = await form(request)
    client_id, client_secret = client_credentials(request, fields)
    if client_id != settings.client_id or not hmac.compare_digest(client_secret, settings.client_secret):
        return JSONResponse({"error": "invalid_client"}, status_code=401, headers=NO_STORE)
    if fields.get("grant_type") != "authorization_code":
        return oauth_error("unsupported_grant_type", "Поддерживается только authorization_code")
    try:
        code = jwt.decode(
            fields.get("code", ""), settings.client_secret, algorithms=["HS256"], audience=CODE_AUDIENCE
        )
    except jwt.PyJWTError:
        return oauth_error("invalid_grant", "Код устарел или повреждён")
    if code["jti"] in used_codes:
        return oauth_error("invalid_grant", "Код уже использован")
    if code["client_id"] != client_id or code["redirect_uri"] != fields.get("redirect_uri"):
        return oauth_error("invalid_grant", "Код выдан другому клиенту")
    if not hmac.compare_digest(pkce_challenge(fields.get("code_verifier", "")), code["code_challenge"]):
        return oauth_error("invalid_grant", "Проверка PKCE не прошла")
    used_codes.add(code["jti"])
    user = users()[code["sub"]]
    common = {
        "iss": settings.issuer,
        "sub": user.sub,
        "aud": client_id,
        "name": user.name,
        "roles": user.roles,
    }
    id_claims = {**common, "nonce": code["nonce"]} if code["nonce"] else common
    return JSONResponse(
        {
            "access_token": signed({**common, "scope": "openid profile"}, ACCESS_TOKEN_LIFETIME),
            "id_token": signed(id_claims, ID_TOKEN_LIFETIME),
            "token_type": "Bearer",
            "expires_in": int(ACCESS_TOKEN_LIFETIME.total_seconds()),
        },
        headers=NO_STORE,
    )


@app.get("/userinfo")
def userinfo(request: Request) -> dict:
    settings = settings_or_404()
    scheme, _, raw = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Нужен токен доступа")
    try:
        claims = jwt.decode(
            raw.strip(),
            private_key().public_key(),
            algorithms=["RS256"],
            audience=settings.client_id,
            issuer=settings.issuer,
        )
    except jwt.PyJWTError as error:
        raise HTTPException(status_code=401, detail="Токен доступа не прошёл проверку") from error
    return {"sub": claims["sub"], "name": claims["name"], "roles": claims["roles"]}


@app.get("/logout")
def logout(post_logout_redirect_uri: str = "") -> RedirectResponse:
    settings = settings_or_404()
    target = post_logout_redirect_uri if post_logout_redirect_uri == settings.public_url + "/" else "/"
    return RedirectResponse(target, status_code=303)
