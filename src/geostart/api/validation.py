from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

VALIDATION_STATUS = 422
FIELD_LABELS = {
    "city": "город",
    "niche": "ниша",
    "lat": "широта",
    "lon": "долгота",
    "area_m2": "площадь",
    "rent_rub_m2_month": "ставка аренды",
    "q": "запрос поиска",
}
LIMIT_MESSAGES = {
    "greater_than": "должно быть больше {gt}",
    "greater_than_equal": "должно быть не меньше {ge}",
    "less_than": "должно быть меньше {lt}",
    "less_than_equal": "должно быть не больше {le}",
}
NUMBER_TYPES = {"float_parsing", "float_type", "int_parsing", "int_type"}
STRING_TYPES = {"string_type"}
GENERIC_MESSAGE = "имеет недопустимое значение"
INVALID_JSON = "Тело запроса не является корректным JSON"
INVALID_BODY = "Тело запроса должно быть объектом JSON с параметрами точки"


def field_label(location: Sequence[Any]) -> str:
    names = [str(part) for part in location if part not in {"body", "query", "path"}]
    if not names:
        return ""
    return FIELD_LABELS.get(names[-1], names[-1])


def readable_limit(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace(".", ",")


def error_message(error: Mapping[str, Any]) -> str:
    error_type = str(error.get("type", ""))
    if error_type == "json_invalid":
        return INVALID_JSON
    if error_type in {"model_attributes_type", "dict_type"}:
        return INVALID_BODY
    label = field_label(error.get("loc", ()))
    if error_type == "missing":
        return f"Не указано поле «{label}»"
    if error_type in LIMIT_MESSAGES:
        limits = {key: readable_limit(value) for key, value in error.get("ctx", {}).items()}
        condition = LIMIT_MESSAGES[error_type].format(**limits)
        return f"Значение поля «{label}» {condition}"
    if error_type in NUMBER_TYPES:
        return f"Значение поля «{label}» должно быть числом"
    if error_type in STRING_TYPES:
        return f"Значение поля «{label}» должно быть строкой"
    return f"Значение поля «{label}» {GENERIC_MESSAGE}"


def russian_detail(errors: Sequence[Mapping[str, Any]]) -> str:
    messages = list(dict.fromkeys(error_message(error) for error in errors))
    return "; ".join(messages)


async def validation_error_handler(request: Request, error: Exception) -> JSONResponse:
    errors = error.errors() if isinstance(error, RequestValidationError) else []
    return JSONResponse(status_code=VALIDATION_STATUS, content={"detail": russian_detail(errors)})
