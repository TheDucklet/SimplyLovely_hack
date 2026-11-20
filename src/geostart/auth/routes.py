import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from geostart.auth import audit, oidc
from geostart.auth.access import current_principal, require, unauthorized
from geostart.auth.models import AccessEntry, AccessStat, CurrentUser
from geostart.auth.roles import Permission
from geostart.auth.settings import AuthSettings, auth_settings
from geostart.auth.tokens import (
    LOGIN_AUDIENCE,
    LOGIN_COOKIE,
    SESSION_COOKIE,
    Principal,
    pkce_pair,
    session_token,
    sign,
    unsign,
)

LOGIN_LIFETIME = timedelta(minutes=10)
LOGIN_PATH = "/api/auth"
LOGOUT_URL = "/api/auth/logout"
NO_ROLES = "У учётной записи нет ролей ГеоСтарт, обратитесь к администратору"

router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


def safe_next(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value


def redirect(url: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    return response


def failure(error: oidc.OidcError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(error))


def on_public_host(request: Request, settings: AuthSettings) -> bool:
    host = request.headers.get("host", "").rsplit(":", 1)[0].strip("[]")
    return not host or host == urlsplit(settings.public_url).hostname


@router.get("/login", summary="Начало входа через сервер банка")
def login(request: Request, next: str | None = None, relay: bool = False) -> RedirectResponse:
    target = safe_next(next)
    settings = auth_settings()
    if not settings.enabled:
        return redirect(target)
    if not relay and not on_public_host(request, settings):
        query = urlencode({"next": target, "relay": "true"})
        return redirect(f"{settings.public_url}{LOGIN_PATH}/login?{query}")
    try:
        endpoint = oidc.provider(settings).authorization_endpoint
    except oidc.OidcError as error:
        raise failure(error) from error
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()
    query = {
        "response_type": "code",
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "scope": "openid profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    response = redirect(f"{endpoint}?{urlencode(query)}")
    pending = {"state": state, "nonce": nonce, "verifier": verifier, "next": target}
    response.set_cookie(
        LOGIN_COOKIE,
        sign(pending, settings.session_secret, LOGIN_AUDIENCE, LOGIN_LIFETIME),
        max_age=int(LOGIN_LIFETIME.total_seconds()),
        path=LOGIN_PATH,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return response


@router.get("/callback", summary="Возврат с сервера входа")
def callback(
    request: Request, code: str | None = None, state: str | None = None, error: str | None = None
) -> RedirectResponse:
    settings = auth_settings()
    if not settings.enabled:
        return redirect("/")
    pending = unsign(request.cookies.get(LOGIN_COOKIE), settings.session_secret, LOGIN_AUDIENCE)
    if error:
        raise unauthorized(f"Сервер входа вернул ошибку {error}")
    if pending is None or not code or not state or not secrets.compare_digest(state, pending["state"]):
        raise unauthorized("Вход устарел или начат в другой вкладке, повторите вход")
    try:
        tokens = oidc.exchange_code(settings, code, pending["verifier"])
        claims = oidc.verify(settings, tokens["id_token"], settings.client_id, nonce=pending["nonce"])
    except oidc.OidcError as failed:
        raise unauthorized(str(failed)) from failed
    roles = oidc.roles_from_claims(settings, claims)
    if not roles:
        raise HTTPException(status_code=403, detail=NO_ROLES)
    principal = Principal(
        subject=claims["sub"],
        name=str(claims.get("name") or claims.get("preferred_username") or ""),
        roles=roles,
        source="session",
    )
    response = redirect(pending["next"])
    response.delete_cookie(LOGIN_COOKIE, path=LOGIN_PATH)
    response.set_cookie(
        SESSION_COOKIE,
        session_token(principal, settings.session_secret, settings.session_hours),
        max_age=int(settings.session_hours * 3600),
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return response


@router.get("/logout", summary="Выход")
def logout() -> RedirectResponse:
    settings = auth_settings()
    target = "/"
    if settings.enabled:
        try:
            end_session = oidc.provider(settings).end_session_endpoint
        except oidc.OidcError:
            end_session = None
        if end_session:
            target = f"{end_session}?{urlencode({'post_logout_redirect_uri': settings.public_url + '/'})}"
    response = redirect(target)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me", summary="Текущий пользователь и его права")
def me(principal: Annotated[Principal, Depends(current_principal)]) -> CurrentUser:
    settings = auth_settings()
    return CurrentUser(
        mode="oidc" if settings.enabled else "off",
        name=principal.name,
        roles=sorted(principal.roles),
        permissions=sorted(principal.permissions),
        logout_url=LOGOUT_URL if settings.enabled else None,
    )


@admin_router.get(
    "/access-log",
    summary="Журнал обращений к отчётам",
    dependencies=[Depends(require(Permission.ACCESS_LOG))],
)
def access_log(
    since: Annotated[date | None, Query(description="С какой даты, по умолчанию 7 дней назад")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[AccessEntry]:
    start = since or datetime.now(UTC).date() - timedelta(days=6)
    return audit.recent(start, limit)


@admin_router.get(
    "/access-stats",
    summary="Число обращений к отчётам по дням, городам и нишам",
    dependencies=[Depends(require(Permission.ACCESS_STATS))],
)
def access_stats(days: Annotated[int, Query(ge=1, le=366)] = 30) -> list[AccessStat]:
    return audit.stats(days)
