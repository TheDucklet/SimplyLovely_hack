from collections.abc import Iterable
from enum import StrEnum


class Role(StrEnum):
    ENTREPRENEUR = "entrepreneur"
    CREDIT_OFFICER = "credit_officer"
    ANALYST = "analyst"
    ADMIN = "admin"


class Permission(StrEnum):
    VIEW_MAP = "view_map"
    LOCATION_REPORT = "location_report"
    CREDIT_CHECK = "credit_check"
    ACCESS_STATS = "access_stats"
    ACCESS_LOG = "access_log"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ENTREPRENEUR: frozenset({Permission.VIEW_MAP, Permission.LOCATION_REPORT}),
    Role.CREDIT_OFFICER: frozenset(
        {Permission.VIEW_MAP, Permission.LOCATION_REPORT, Permission.CREDIT_CHECK}
    ),
    Role.ANALYST: frozenset({Permission.VIEW_MAP, Permission.LOCATION_REPORT, Permission.ACCESS_STATS}),
    Role.ADMIN: frozenset(
        {Permission.VIEW_MAP, Permission.LOCATION_REPORT, Permission.ACCESS_STATS, Permission.ACCESS_LOG}
    ),
}


def permissions_of(roles: Iterable[Role]) -> frozenset[Permission]:
    granted: set[Permission] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS[role]
    return frozenset(granted)
