from typing import Literal

from pydantic import BaseModel, Field

from geostart.auth.roles import Permission, Role


class CurrentUser(BaseModel):
    mode: Literal["off", "oidc"] = Field(description="off – вход выключен, oidc – вход через сервер банка")
    name: str
    roles: list[Role]
    permissions: list[Permission]
    logout_url: str | None


class AccessEntry(BaseModel):
    time: str = Field(description="Время ответа в UTC")
    request_id: str
    user: str | None = Field(description="Псевдоним пользователя, HMAC от идентификатора сервера входа")
    roles: list[str]
    action: str
    city: str | None
    niche: str | None
    status: int
    duration_ms: int


class AccessStat(BaseModel):
    date: str
    action: str
    city: str | None
    niche: str | None
    outcome: Literal["ok", "denied", "error"]
    count: int
