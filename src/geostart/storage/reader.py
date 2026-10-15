from geostart.schemas import AddressMatch, Competitor, HexesResponse, HexScore
from geostart.storage.connection import DatabaseRole, connect

SEARCH_LIMIT = 10
UNKNOWN_DATA_VERSION = "нет данных"

HEXES_QUERY = """
SELECT
    s.h3,
    s.revenue_p50,
    s.payback_months_p50,
    s.risk_level,
    s.competitors_500m
FROM geo.scores AS s
WHERE s.city = %(city)s
    AND s.niche = %(niche)s
ORDER BY s.h3
"""

COMPETITORS_QUERY = """
SELECT
    c.name,
    c.brand,
    c.lat,
    c.lon,
    c.source
FROM geo.competitors AS c
WHERE c.city = %(city)s
    AND c.niche = %(niche)s
ORDER BY c.poi_id
"""

SEARCH_QUERY = """
SELECT
    a.address,
    a.lat,
    a.lon
FROM geo.addresses AS a
WHERE a.city = %(city)s
    AND a.address_search LIKE ALL (%(patterns)s)
ORDER BY
    split_part(split_part(a.address_search, ', ', 2), ' ', 1) = ANY (%(tokens)s) DESC,
    a.address_search LIKE %(prefix)s DESC,
    a.address
LIMIT %(limit)s
"""

VERSION_QUERY = """
SELECT
    max(v.data_version) AS data_version
FROM geo.data_versions AS v
"""

CITY_VERSION_QUERY = """
SELECT
    v.data_version
FROM geo.data_versions AS v
WHERE v.city = %(city)s
"""


class CityNotLoadedError(LookupError):
    pass


def escape_like(token: str) -> str:
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_tokens(query: str) -> list[str]:
    normalized = query.lower().replace("ё", "е")
    return [token.strip(",.") for token in normalized.split() if token.strip(",.")]


def city_data_version(city_code: str) -> str:
    with connect(DatabaseRole.API) as connection:
        row = connection.execute(CITY_VERSION_QUERY, {"city": city_code}).fetchone()
    return row[0] if row else UNKNOWN_DATA_VERSION


def latest_data_version() -> str:
    with connect(DatabaseRole.API) as connection:
        row = connection.execute(VERSION_QUERY).fetchone()
    return row[0] if row and row[0] else UNKNOWN_DATA_VERSION


def db_hexes(city_code: str, niche_code: str) -> HexesResponse:
    with connect(DatabaseRole.API) as connection:
        rows = connection.execute(HEXES_QUERY, {"city": city_code, "niche": niche_code}).fetchall()
        version_row = connection.execute(CITY_VERSION_QUERY, {"city": city_code}).fetchone()
    if not rows:
        raise CityNotLoadedError(
            f"Город {city_code} для ниши {niche_code} не загружен в базу, запустите "
            f"uv run python -m geostart.storage load --city {city_code}"
        )
    items = [
        HexScore(
            h3=h3,
            revenue_p50=round(revenue),
            payback_months_p50=payback,
            risk_level=risk,
            competitors_500m=competitors,
        )
        for h3, revenue, payback, risk, competitors in rows
    ]
    return HexesResponse(
        city=city_code,
        niche=niche_code,
        data_version=version_row[0] if version_row else UNKNOWN_DATA_VERSION,
        items=items,
    )


def db_competitors(city_code: str, niche_code: str) -> list[Competitor]:
    with connect(DatabaseRole.API) as connection:
        rows = connection.execute(COMPETITORS_QUERY, {"city": city_code, "niche": niche_code}).fetchall()
    return [
        Competitor(name=name, brand=brand, lat=lat, lon=lon, source=source)
        for name, brand, lat, lon, source in rows
    ]


def db_search(city_code: str, query: str) -> list[AddressMatch]:
    tokens = search_tokens(query)
    if not tokens:
        return []
    parameters = {
        "city": city_code,
        "patterns": [f"%{escape_like(token)}%" for token in tokens],
        "tokens": tokens,
        "prefix": f"{escape_like(tokens[0])}%",
        "limit": SEARCH_LIMIT,
    }
    with connect(DatabaseRole.API) as connection:
        rows = connection.execute(SEARCH_QUERY, parameters).fetchall()
    return [AddressMatch(address=address, lat=lat, lon=lon) for address, lat, lon in rows]
