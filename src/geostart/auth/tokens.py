import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from geostart.auth.roles import Permission, Role, permissions_of

SESSION_COOKIE = "geostart_session"
LOGIN_COOKIE = "geostart_login"
SESSION_AUDIENCE = "geostart-session"
LOGIN_AUDIENCE = "geostart-login"
PSEUDONYM_LENGTH = 16


@dataclass(frozen=True)
class Principal:
    subject: str
    name: str
    roles: frozenset[Role]
    source: str

    @property
    def permissions(self) -> frozenset[Permission]:
        return permissions_of(self.roles)


def sign(payload: dict, secret: str, audience: str, lifetime: timedelta) -> str:
    now = datetime.now(UTC)
    claims = {**payload, "aud": audience, "iat": now, "exp": now + lifetime}
    return jwt.encode(claims, secret, algorithm="HS256")


def unsign(token: str | None, secret: str, audience: str) -> dict | None:
    if not token:
        return None
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], audience=audience)
    except jwt.PyJWTError:
        return None


def session_token(principal: Principal, secret: str, hours: float) -> str:
    payload = {"sub": principal.subject, "name": principal.name, "roles": sorted(principal.roles)}
    return sign(payload, secret, SESSION_AUDIENCE, timedelta(hours=hours))


def session_principal(token: str | None, secret: str) -> Principal | None:
    claims = unsign(token, secret, SESSION_AUDIENCE)
    if claims is None:
        return None
    roles = frozenset(Role(role) for role in claims.get("roles", []) if role in Role)
    return Principal(subject=claims["sub"], name=claims.get("name", ""), roles=roles, source="session")


def pseudonym(subject: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), subject.encode(), hashlib.sha256).hexdigest()
    return digest[:PSEUDONYM_LENGTH]


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    return verifier, pkce_challenge(verifier)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
