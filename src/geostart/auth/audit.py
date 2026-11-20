import json
import os
import time
import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Lock

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from geostart.auth.models import AccessEntry, AccessStat
from geostart.auth.settings import auth_settings
from geostart.auth.tokens import Principal, pseudonym
from geostart.config import load_cities, load_niches
from geostart.settings import data_dir

AUDITED_PATHS = {
    "/api/v1/report": "location_report",
    "/api/v2/economics": "economics",
    "/api/v2/credit-check": "credit_check",
    "/api/v2/sensitivity": "sensitivity",
}
MAX_BODY_BYTES = 65_536
UNKNOWN = "unknown"
_write_lock = Lock()


def audit_dir() -> Path:
    return Path(os.environ.get("GEOSTART_AUDIT_DIR") or data_dir() / "audit")


def known(value: object, codes: set[str]) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) and value in codes else UNKNOWN


def place(body: bytes) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(body)
    except ValueError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    if isinstance(payload.get("economics"), dict):
        payload = payload["economics"]
    cities = {city.code for city in load_cities()}
    niches = {niche.code for niche in load_niches()}
    return known(payload.get("city"), cities), known(payload.get("niche"), niches)


def user_fields(principal: Principal | None) -> tuple[str | None, list[str]]:
    if principal is None:
        return None, []
    return pseudonym(principal.subject, auth_settings().session_secret), sorted(principal.roles)


def write(entry: AccessEntry) -> None:
    folder = audit_dir()
    path = folder / f"access-{entry.time[:10]}.jsonl"
    line = entry.model_dump_json() + "\n"
    with _write_lock:
        folder.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line)


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        action = AUDITED_PATHS.get(scope.get("path", "")) if scope["type"] == "http" else None
        if action is None or not auth_settings().enabled:
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        body = bytearray()
        status = 500

        async def capture_receive() -> Message:
            message = await receive()
            if message["type"] == "http.request" and len(body) < MAX_BODY_BYTES:
                body.extend(message.get("body", b"")[: MAX_BODY_BYTES - len(body)])
            return message

        async def capture_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, capture_receive, capture_send)
        finally:
            city, niche = place(bytes(body))
            user, roles = user_fields(scope.get("state", {}).get("principal"))
            write(
                AccessEntry(
                    time=datetime.now(UTC).isoformat(timespec="seconds"),
                    request_id=uuid.uuid4().hex,
                    user=user,
                    roles=roles,
                    action=action,
                    city=city,
                    niche=niche,
                    status=status,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                )
            )


def log_files(since: date) -> list[Path]:
    folder = audit_dir()
    if not folder.exists():
        return []
    return sorted(
        (
            path
            for path in folder.glob("access-*.jsonl")
            if path.stem.removeprefix("access-") >= since.isoformat()
        ),
        reverse=True,
    )


def entries(since: date) -> Iterator[AccessEntry]:
    for path in log_files(since):
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            if line.strip():
                yield AccessEntry.model_validate_json(line)


def recent(since: date, limit: int) -> list[AccessEntry]:
    found = []
    for entry in entries(since):
        found.append(entry)
        if len(found) >= limit:
            break
    return found


def outcome(status: int) -> str:
    if status < 400:
        return "ok"
    return "denied" if status in (401, 403) else "error"


def stats(days: int) -> list[AccessStat]:
    since = datetime.now(UTC).date() - timedelta(days=days - 1)
    counts = Counter(
        (entry.time[:10], entry.action, entry.city, entry.niche, outcome(entry.status))
        for entry in entries(since)
    )
    return [
        AccessStat(date=day, action=action, city=city, niche=niche, outcome=result, count=count)
        for (day, action, city, niche, result), count in sorted(
            counts.items(),
            key=lambda item: (item[0][0], item[0][1], item[0][2] or "", item[0][3] or "", item[0][4]),
        )
    ]
