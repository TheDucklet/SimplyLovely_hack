from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from geostart.auth import oidc
from geostart.auth.roles import Permission, Role
from geostart.auth.settings import AuthSettings, auth_settings
from geostart.auth.tokens import SESSION_COOKIE, Principal, session_principal

ANONYMOUS = Principal(subject="anonymous", name="Без входа", roles=frozenset(Role), source="off")
LOGIN_REQUIRED = "Требуется вход в ГеоСтарт"


def unauthorized(detail: str = LOGIN_REQUIRED) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def bearer_principal(settings: AuthSettings, token: str) -> Principal:
    try:
        claims = oidc.verify(settings, token, settings.audience)
    except oidc.OidcError as error:
        raise unauthorized(str(error)) from error
    return Principal(
        subject=claims["sub"],
        name=str(claims.get("name") or claims.get("preferred_username") or ""),
        roles=oidc.roles_from_claims(settings, claims),
        source="bearer",
    )


def resolve_principal(request: Request) -> Principal | None:
    settings = auth_settings()
    if not settings.enabled:
        return ANONYMOUS
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token:
        return bearer_principal(settings, token.strip())
    return session_principal(request.cookies.get(SESSION_COOKIE), settings.session_secret)


def current_principal(request: Request) -> Principal:
    principal = resolve_principal(request)
    if principal is None:
        raise unauthorized()
    request.state.principal = principal
    return principal


def require(permission: Permission) -> Callable[[Principal], Principal]:
    def check(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if permission not in principal.permissions:
            raise HTTPException(status_code=403, detail="Недостаточно прав для этого действия")
        return principal

    return check
