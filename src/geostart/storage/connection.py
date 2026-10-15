import os
from enum import StrEnum

import psycopg

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "55433"
DEFAULT_DATABASE = "geostart"
CONNECT_TIMEOUT_SECONDS = 5


class DatabaseRole(StrEnum):
    LOADER = "geostart_loader"
    API = "geostart_api"


PASSWORD_VARIABLES = {
    DatabaseRole.LOADER: "GEOSTART_DB_LOADER_PASSWORD",
    DatabaseRole.API: "GEOSTART_DB_API_PASSWORD",
}


class DatabaseNotConfiguredError(RuntimeError):
    pass


def connection_parameters(role: DatabaseRole) -> dict[str, str | int]:
    password = os.environ.get(PASSWORD_VARIABLES[role])
    if not password:
        raise DatabaseNotConfiguredError(
            f"Не задан пароль роли {role.value}, добавьте {PASSWORD_VARIABLES[role]} в .env"
        )
    return {
        "host": os.environ.get("GEOSTART_DB_HOST", DEFAULT_HOST),
        "port": os.environ.get("GEOSTART_DB_PORT", DEFAULT_PORT),
        "dbname": os.environ.get("GEOSTART_DB_NAME", DEFAULT_DATABASE),
        "user": role.value,
        "password": password,
        "connect_timeout": CONNECT_TIMEOUT_SECONDS,
        "application_name": f"geostart-{role.name.lower()}",
    }


def connect(role: DatabaseRole) -> psycopg.Connection:
    return psycopg.connect(**connection_parameters(role))
