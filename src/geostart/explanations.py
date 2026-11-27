import json
import logging
import os
import re
from decimal import Decimal, InvalidOperation
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from geostart.schemas import LocationReport
from geostart.settings import TRUE_VALUES

logger = logging.getLogger(__name__)
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
NUMBER_PATTERN = re.compile(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?")


def explanation_enabled() -> bool:
    return os.environ.get("GEOSTART_EXPLANATIONS", "false").strip().lower() in TRUE_VALUES


def explanation_url() -> str:
    return os.environ.get("GEOSTART_EXPLANATION_URL", "http://127.0.0.1:11434/api/generate").strip()


def explanation_model() -> str:
    return os.environ.get("GEOSTART_EXPLANATION_MODEL", "qwen2.5:3b").strip()


def explanation_timeout() -> float:
    raw = os.environ.get("GEOSTART_EXPLANATION_TIMEOUT", "10").strip()
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError("GEOSTART_EXPLANATION_TIMEOUT должен быть числом") from error
    if value <= 0:
        raise ValueError("GEOSTART_EXPLANATION_TIMEOUT должен быть положительным")
    return value


def ensure_local_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOCAL_HOSTS:
        raise ValueError("Локальные пояснения разрешают только адрес 127.0.0.1, localhost или ::1")


def number_forms(value: str) -> set[str]:
    normalized = value.replace(",", ".")
    try:
        decimal = Decimal(normalized)
    except InvalidOperation:
        return {value, normalized}
    plain = format(decimal, "f").rstrip("0").rstrip(".") or "0"
    forms = {value, normalized, plain, plain.replace(".", ",")}
    return forms


def report_numbers(report: LocationReport) -> set[str]:
    payload = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
    numbers: set[str] = set()
    for token in NUMBER_PATTERN.findall(payload):
        numbers.update(number_forms(token))
    return numbers


def validate_explanation(text: str, report: LocationReport) -> bool:
    if not text.strip() or len(text) > 2000:
        return False
    allowed = report_numbers(report)
    return all(token in allowed for token in NUMBER_PATTERN.findall(text))


def prompt_for(report: LocationReport) -> str:
    payload = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
    return (
        "Составь короткое пояснение отчёта ГеоСтарта на русском языке в 2-4 предложениях. "
        "Опирайся только на JSON ниже. Не придумывай факты и числа. "
        "Числа используй только в точном виде из JSON. "
        "Объясни риск, главный фактор выручки и одно существенное допущение. JSON отчёта:\n" + payload
    )


def response_text(payload: dict[str, object]) -> str | None:
    response = payload.get("response")
    if isinstance(response, str):
        return response
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
    return None


def generate_explanation(report: LocationReport) -> str | None:
    if not explanation_enabled():
        return None
    url = explanation_url()
    try:
        ensure_local_url(url)
        body = json.dumps(
            {"model": explanation_model(), "prompt": prompt_for(report), "stream": False},
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(url, data=body, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=explanation_timeout()) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = response_text(payload) if isinstance(payload, dict) else None
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        logger.warning("Локальное пояснение недоступно: %s", error)
        return None
    if text is None or not validate_explanation(text, report):
        logger.warning("Локальное пояснение отклонено проверкой чисел")
        return None
    return text.strip()
