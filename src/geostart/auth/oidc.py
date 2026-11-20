import time
from dataclasses import dataclass
from threading import Lock

import httpx
import jwt

from geostart.auth.roles import Role
from geostart.auth.settings import AuthSettings

CACHE_SECONDS = 600
ALGORITHMS = ["RS256", "PS256", "ES256"]
CLOCK_SKEW_SECONDS = 60


class OidcError(RuntimeError):
    pass


@dataclass(frozen=True)
class Provider:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: str | None


_providers: dict[str, tuple[float, Provider]] = {}
_key_sets: dict[str, tuple[float, jwt.PyJWKSet]] = {}
_lock = Lock()


def http_client() -> httpx.Client:
    return httpx.Client(timeout=10)


def reset_cache() -> None:
    with _lock:
        _providers.clear()
        _key_sets.clear()


def backchannel(settings: AuthSettings, url: str) -> str:
    if settings.internal_url and url.startswith(settings.issuer):
        return settings.internal_url + url[len(settings.issuer) :]
    return url


def fetch_json(settings: AuthSettings, url: str) -> dict:
    client = http_client()
    try:
        response = client.get(backchannel(settings, url))
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise OidcError(f"Сервер входа недоступен: {url}") from error
    finally:
        client.close()


def provider(settings: AuthSettings) -> Provider:
    cached = _providers.get(settings.issuer)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    document = fetch_json(settings, settings.issuer + "/.well-known/openid-configuration")
    if document.get("issuer", "").rstrip("/") != settings.issuer:
        raise OidcError("Издатель в настройках сервера входа не совпадает с GEOSTART_OIDC_ISSUER")
    found = Provider(
        issuer=settings.issuer,
        authorization_endpoint=document["authorization_endpoint"],
        token_endpoint=document["token_endpoint"],
        jwks_uri=document["jwks_uri"],
        end_session_endpoint=document.get("end_session_endpoint"),
    )
    with _lock:
        _providers[settings.issuer] = (time.monotonic(), found)
    return found


def key_set(settings: AuthSettings, refresh: bool = False) -> jwt.PyJWKSet:
    cached = _key_sets.get(settings.issuer)
    if cached and not refresh and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    keys = jwt.PyJWKSet.from_dict(fetch_json(settings, provider(settings).jwks_uri))
    with _lock:
        _key_sets[settings.issuer] = (time.monotonic(), keys)
    return keys


def signing_key(settings: AuthSettings, token: str) -> jwt.PyJWK:
    try:
        key_id = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError as error:
        raise OidcError("Токен повреждён") from error
    for refresh in (False, True):
        for key in key_set(settings, refresh).keys:
            if key_id is None or key.key_id == key_id:
                return key
    raise OidcError("Ключ подписи токена не найден у сервера входа")


def verify(settings: AuthSettings, token: str, audience: str, nonce: str | None = None) -> dict:
    key = signing_key(settings, token)
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=ALGORITHMS,
            audience=audience,
            issuer=settings.issuer,
            leeway=CLOCK_SKEW_SECONDS,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as error:
        raise OidcError(f"Токен не прошёл проверку: {error}") from error
    if nonce is not None and claims.get("nonce") != nonce:
        raise OidcError("Токен выдан не на этот вход")
    return claims


def exchange_code(settings: AuthSettings, code: str, verifier: str) -> dict:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.redirect_uri,
        "code_verifier": verifier,
    }
    endpoint = backchannel(settings, provider(settings).token_endpoint)
    client = http_client()
    try:
        response = client.post(endpoint, data=form, auth=(settings.client_id, settings.client_secret))
    except httpx.HTTPError as error:
        raise OidcError("Сервер входа недоступен") from error
    finally:
        client.close()
    if response.status_code != 200:
        raise OidcError(f"Сервер входа отклонил код авторизации, ответ {response.status_code}")
    tokens = response.json()
    if "id_token" not in tokens:
        raise OidcError("Сервер входа не вернул id_token")
    return tokens


def claim(claims: dict, path: str) -> object:
    value: object = claims
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def roles_from_claims(settings: AuthSettings, claims: dict) -> frozenset[Role]:
    raw = claim(claims, settings.roles_claim)
    values = raw.split() if isinstance(raw, str) else raw if isinstance(raw, list) else []
    mapped = {settings.role_map.get(str(value), str(value)) for value in values}
    return frozenset(Role(value) for value in mapped if value in Role)
