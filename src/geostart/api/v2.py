from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Query

from geostart.api import mocks
from geostart.api.data_backend import DataNotReadyError
from geostart.config import UnknownCityError, UnknownNicheError, get_city
from geostart.economics.sensitivity import evaluate_sensitivity
from geostart.economics.service import check_plan, credit_products, evaluate_economics, norms_response
from geostart.schemas import ReportRequest
from geostart.schemas_v2 import (
    CreditCheckReport,
    CreditCheckRequest,
    CreditProductInfo,
    EconomicsReport,
    EconomicsRequest,
    Estimate,
    GeoDemand,
    NormsResponse,
    RevenueDemand,
    SensitivityReport,
    SensitivityRequest,
)
from geostart.settings import use_mocks

MOCK_PROVIDER = "демо-режим без данных города"
PROBLEM_RESPONSES = {
    404: {"description": "Город, ниша или данные не найдены", "content": {"application/problem+json": {}}},
    422: {"description": "Параметры расчёта некорректны", "content": {"application/problem+json": {}}},
}

router = APIRouter(prefix="/api/v2", tags=["v2"], responses=PROBLEM_RESPONSES)


def guarded[ResultT](load: Callable[[], ResultT]) -> ResultT:
    try:
        return load()
    except (UnknownCityError, UnknownNicheError, DataNotReadyError, FileNotFoundError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (mocks.PointOutsideCityError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def with_mock_demand[RequestT: EconomicsRequest](request: RequestT) -> RequestT:
    demand = request.demand
    if not use_mocks() or not isinstance(demand, GeoDemand):
        return request
    report = mocks.mock_report(
        get_city(request.city),
        ReportRequest(
            city=request.city,
            niche=request.niche,
            lat=demand.lat,
            lon=demand.lon,
            area_m2=request.premises.area_m2,
            rent_rub_m2_month=request.premises.rent_rub_m2_month,
        ),
    )
    revenue = report.revenue_month
    replacement = RevenueDemand(
        source="revenue",
        revenue_month=Estimate(p10=revenue.p10, p50=revenue.p50, p90=revenue.p90),
        provider=MOCK_PROVIDER,
    )
    return request.model_copy(update={"demand": replacement})


@router.post("/economics", summary="Финансовая модель точки")
def economics(request: EconomicsRequest) -> EconomicsReport:
    return guarded(lambda: evaluate_economics(with_mock_demand(request)))


@router.post("/sensitivity", summary="Анализ чувствительности финансовой модели")
def sensitivity(request: SensitivityRequest) -> SensitivityReport:
    return guarded(lambda: evaluate_sensitivity(with_mock_demand(request)))


@router.post("/credit-check", summary="Проверка бизнес-плана заявки на кредит")
def credit_check(request: CreditCheckRequest) -> CreditCheckReport:
    return guarded(
        lambda: check_plan(request.model_copy(update={"economics": with_mock_demand(request.economics)}))
    )


@router.get("/norms/{niche}", summary="Нормативы и параметры ниши в городе")
def norms(niche: str, city: str = Query(min_length=1)) -> NormsResponse:
    return guarded(lambda: norms_response(city, niche))


@router.get("/credit-products", summary="Кредитные продукты и их условия с источниками")
def products() -> list[CreditProductInfo]:
    return guarded(credit_products)
