import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class CheckResult:
    name: str
    url: str
    status: int | None
    expected: tuple[int, ...]
    ok: bool
    error: str | None = None


CHECKS = (
    ("страница", "/", (200,)),
    ("здоровье API", "/api/v1/health", (200,)),
    ("тайл подложки", "/basemap/tiles/geostart/10/618/320.mvt", (200,)),
    ("единый вход", "/api/auth/login", (200, 303, 307)),
)


def check_endpoint(
    base_url: str, name: str, path: str, expected: tuple[int, ...], timeout: float
) -> CheckResult:
    url = f"{base_url}{path}"
    request = Request(url, headers={"User-Agent": "geostart-stand-health/1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
    except HTTPError as error:
        status = error.code
    except (TimeoutError, URLError, OSError) as error:
        return CheckResult(name, url, None, expected, False, str(error))
    return CheckResult(name, url, status, expected, status in expected)


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка доступности публичного стенда ГеоСтарта")
    parser.add_argument("--url", default=os.getenv("GEOSTART_PUBLIC_URL", "http://fintech.shenti.space"))
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    base_url = args.url.rstrip("/")
    results = [
        check_endpoint(base_url, name, path, expected, args.timeout) for name, path, expected in CHECKS
    ]
    if args.json:
        print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    else:
        for result in results:
            status = result.status if result.status is not None else "нет ответа"
            state = "OK" if result.ok else "ОШИБКА"
            detail = f": {result.error}" if result.error else ""
            print(f"{state} {result.name}: {status}{detail}")
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
