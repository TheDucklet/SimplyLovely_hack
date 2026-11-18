from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException

VALIDATION_STATUS = 422
FIELD_LABELS = {
    "city": "город",
    "niche": "ниша",
    "lat": "широта",
    "lon": "долгота",
    "area_m2": "площадь",
    "rent_rub_m2_month": "ставка аренды",
    "q": "запрос поиска",
    "demand": "спрос",
    "source": "источник спроса",
    "revenue_month": "выручка в месяц",
    "visitors_per_day": "трафик в день",
    "conversion": "конверсия",
    "avg_check_rub": "средний чек",
    "provider": "поставщик оценки",
    "security_deposit_months": "обеспечительный платёж",
    "central_district": "центральный округ",
    "staff_count": "число сотрудников",
    "salary_rub_month": "зарплата",
    "cogs_share": "доля себестоимости",
    "other_opex_rub_month": "прочие расходы",
    "capex_rub": "вложения",
    "working_capital_rub": "оборотный запас",
    "loan_amount_rub": "сумма кредита",
    "loan_share": "доля кредита",
    "rate_annual": "ставка кредита",
    "term_months": "срок кредита",
    "schedule": "график платежей",
    "legal_form": "форма бизнеса",
    "regime": "налоговый режим",
    "horizon_months": "горизонт расчёта",
    "start_month": "месяц открытия",
    "discount_rate_annual": "ставка дисконтирования",
    "revenue_month_rub": "выручка плана",
    "payback_months": "окупаемость плана",
    "economics": "параметры расчёта",
    "plan": "бизнес-план",
    "p10": "p10",
    "p50": "p50",
    "p90": "p90",
}
V2_PREFIX = "/api/v2"
PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_TITLES = {
    404: "Не найдено",
    422: "Некорректные параметры расчёта",
    503: "Сервис данных недоступен",
}
DEFAULT_PROBLEM_TITLE = "Ошибка запроса"
VALUE_ERROR_PREFIX = "Value error, "
LIMIT_MESSAGES = {
    "greater_than": "должно быть больше {gt}",
    "greater_than_equal": "должно быть не меньше {ge}",
    "less_than": "должно быть меньше {lt}",
    "less_than_equal": "должно быть не больше {le}",
}
NUMBER_TYPES = {"float_parsing", "float_type", "int_parsing", "int_type"}
STRING_TYPES = {"string_type"}
CHOICE_TYPES = {"literal_error", "enum"}
TAG_TYPES = {"union_tag_invalid", "union_tag_not_found"}
INTEGER_TYPES = {"int_from_float"}
BOOLEAN_TYPES = {"bool_parsing", "bool_type"}
GENERIC_MESSAGE = "имеет недопустимое значение"
INVALID_JSON = "Тело запроса не является корректным JSON"
INVALID_BODY = "Тело запроса должно быть объектом JSON с параметрами точки"


def field_names(location: Sequence[Any]) -> list[str]:
    return [str(part) for part in location if part not in {"body", "query", "path"}]


def field_label(location: Sequence[Any]) -> str:
    names = [name for name in field_names(location) if name not in {"geostart", "revenue", "traffic"}]
    if not names:
        return ""
    return FIELD_LABELS.get(names[-1], names[-1])


def field_path(location: Sequence[Any]) -> str:
    return ".".join(name for name in field_names(location) if name not in {"geostart", "revenue", "traffic"})


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
    if error_type in INTEGER_TYPES:
        return f"Значение поля «{label}» должно быть целым числом"
    if error_type in BOOLEAN_TYPES:
        return f"Значение поля «{label}» должно быть true или false"
    if error_type in CHOICE_TYPES:
        expected = str(error.get("ctx", {}).get("expected", "")).replace("'", "")
        return f"Значение поля «{label}» должно быть одним из {expected}"
    if error_type in TAG_TYPES:
        return "Поле «источник спроса» должно быть одним из geostart, revenue, traffic"
    if error_type == "extra_forbidden":
        return f"Поле «{label}» не поддерживается"
    if error_type == "value_error":
        return str(error.get("msg", "")).removeprefix(VALUE_ERROR_PREFIX)
    return f"Значение поля «{label}» {GENERIC_MESSAGE}"


def russian_detail(errors: Sequence[Mapping[str, Any]]) -> str:
    messages = list(dict.fromkeys(error_message(error) for error in errors))
    return "; ".join(messages)


def is_v2(request: Request) -> bool:
    return request.url.path.startswith(V2_PREFIX)


def problem(status: int, detail: str, errors: list[dict[str, str]] | None = None) -> JSONResponse:
    content: dict[str, Any] = {
        "type": "about:blank",
        "title": PROBLEM_TITLES.get(status, DEFAULT_PROBLEM_TITLE),
        "status": status,
        "detail": detail,
    }
    if errors is not None:
        content["errors"] = errors
    return JSONResponse(status_code=status, content=content, media_type=PROBLEM_MEDIA_TYPE)


async def validation_error_handler(request: Request, error: Exception) -> JSONResponse:
    errors = error.errors() if isinstance(error, RequestValidationError) else []
    if is_v2(request):
        items = [
            {"field": field_path(item.get("loc", ())), "message": error_message(item)} for item in errors
        ]
        return problem(VALIDATION_STATUS, russian_detail(errors), items)
    return JSONResponse(status_code=VALIDATION_STATUS, content={"detail": russian_detail(errors)})


async def http_error_handler(request: Request, error: Exception) -> Response:
    if not isinstance(error, HTTPException):
        raise error
    if is_v2(request):
        return problem(error.status_code, str(error.detail))
    return await http_exception_handler(request, error)
