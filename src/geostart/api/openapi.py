import json
import re

from geostart.api.main import app
from geostart.settings import REPOSITORY_ROOT

OPENAPI_V2_PATH = REPOSITORY_ROOT / "docs" / "api-v2.openapi.json"
V2_PREFIX = "/api/v2"
REFERENCE = re.compile(r'"#/components/schemas/([^"]+)"')


def referenced(schemas: dict, roots: set[str]) -> set[str]:
    found: set[str] = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in found or name not in schemas:
            continue
        found.add(name)
        pending.extend(REFERENCE.findall(json.dumps(schemas[name])))
    return found


def v2_schema() -> dict:
    full = app.openapi()
    paths = {path: item for path, item in full["paths"].items() if path.startswith(V2_PREFIX)}
    schemas = full.get("components", {}).get("schemas", {})
    names = referenced(schemas, set(REFERENCE.findall(json.dumps(paths))))
    return {
        "openapi": full["openapi"],
        "info": {"title": "ГеоСтарт API v2", "version": full["info"]["version"]},
        "paths": paths,
        "components": {"schemas": {name: schemas[name] for name in sorted(names)}},
    }


def main() -> None:
    OPENAPI_V2_PATH.write_text(
        json.dumps(v2_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Контракт API v2 записан в {OPENAPI_V2_PATH}")


if __name__ == "__main__":
    main()
