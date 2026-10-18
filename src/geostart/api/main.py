from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import psycopg
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from geostart.api import data_backend, mocks
from geostart.api.validation import validation_error_handler
from geostart.config import (
    CityConfig,
    NicheConfig,
    UnknownCityError,
    UnknownNicheError,
    get_city,
    get_niche,
    load_cities,
    load_niches,
)
from geostart.model.data import configure_environment
from geostart.schemas import (
    AddressMatch,
    CityInfo,
    Competitor,
    HealthResponse,
    HexesResponse,
    LocationReport,
    NicheInfo,
    ReportRequest,
)
from geostart.settings import cors_origins, use_mocks, warmup_enabled
from geostart.storage import reader
from geostart.storage.connection import DatabaseNotConfiguredError

GZIP_MINIMUM_BYTES = 1000
DATABASE_UNAVAILABLE = (
    "База данных недоступна, проверьте docker compose up -d db и параметры GEOSTART_DB_* в .env"
)

router = APIRouter(prefix="/api/v1")


def resolve_city(code: str) -> CityConfig:
    try:
        return get_city(code)
    except UnknownCityError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def resolve_niche(code: str) -> NicheConfig:
    try:
        return get_niche(code)
    except UnknownNicheError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def from_data[ResponseT](load: Callable[[], ResponseT]) -> ResponseT:
    try:
        return load()
    except (data_backend.DataNotReadyError, reader.CityNotLoadedError, FileNotFoundError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except DatabaseNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except psycopg.OperationalError as error:
        raise HTTPException(status_code=503, detail=DATABASE_UNAVAILABLE) from error


@router.get("/health")
def health() -> HealthResponse:
    if use_mocks():
        return HealthResponse(status="ok", mode="mocks", data_version=mocks.MOCK_DATA_VERSION)
    city_codes = [city.code for city in load_cities()]
    version = from_data(lambda: data_backend.latest_data_version(city_codes))
    return HealthResponse(status="ok", mode="data", data_version=version)


@router.get("/cities")
def cities() -> list[CityInfo]:
    return [
        CityInfo(code=city.code, name=city.name, center=city.center, zoom=city.zoom) for city in load_cities()
    ]


@router.get("/niches")
def niches() -> list[NicheInfo]:
    return [NicheInfo(code=niche.code, name=niche.name) for niche in load_niches()]


@router.get("/hexes")
def hexes(city: str, niche: str) -> HexesResponse:
    city_code = resolve_city(city).code
    niche_code = resolve_niche(niche).code
    if use_mocks():
        return mocks.mock_hexes(city_code, niche_code)
    return from_data(lambda: data_backend.data_hexes(city_code, niche_code))


@router.get("/competitors")
def competitors(city: str, niche: str) -> list[Competitor]:
    city_code = resolve_city(city).code
    niche_code = resolve_niche(niche).code
    if use_mocks():
        return mocks.mock_competitors(city_code, niche_code)
    return from_data(lambda: data_backend.data_competitors(city_code, niche_code))


@router.get("/search")
def search(city: str, q: str = Query(min_length=1)) -> list[AddressMatch]:
    city_code = resolve_city(city).code
    if use_mocks():
        return mocks.mock_search(city_code, q)
    return from_data(lambda: data_backend.data_search(city_code, q))


@router.post("/report")
def report(request: ReportRequest) -> LocationReport:
    city_config = resolve_city(request.city)
    resolve_niche(request.niche)
    try:
        if use_mocks():
            return mocks.mock_report(city_config, request)
        return from_data(lambda: data_backend.data_report(city_config, request))
    except (mocks.PointOutsideCityError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if warmup_enabled() and not use_mocks():
        data_backend.warm_model_cache()
    yield


configure_environment()
app = FastAPI(title="ГеоСтарт API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=cors_origins(), allow_methods=["GET", "POST"], allow_headers=["*"]
)
app.add_middleware(GZipMiddleware, minimum_size=GZIP_MINIMUM_BYTES)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(router)
