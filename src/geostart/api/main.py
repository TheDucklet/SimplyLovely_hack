from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from geostart.api import mocks
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
from geostart.settings import cors_origins, use_mocks

REAL_DATA_NOT_READY = (
    "Расчёты на реальных данных ещё не подключены, запустите API с переменной GEOSTART_USE_MOCKS=true"
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


def require_mocks() -> None:
    if not use_mocks():
        raise HTTPException(status_code=503, detail=REAL_DATA_NOT_READY)


@router.get("/health")
def health() -> HealthResponse:
    mode = "mocks" if use_mocks() else "data"
    return HealthResponse(status="ok", mode=mode, data_version=mocks.MOCK_DATA_VERSION)


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
    city_config = resolve_city(city)
    niche_config = resolve_niche(niche)
    require_mocks()
    return mocks.mock_hexes(city_config.code, niche_config.code)


@router.get("/competitors")
def competitors(city: str, niche: str) -> list[Competitor]:
    city_config = resolve_city(city)
    niche_config = resolve_niche(niche)
    require_mocks()
    return mocks.mock_competitors(city_config.code, niche_config.code)


@router.get("/search")
def search(city: str, q: str = Query(min_length=1)) -> list[AddressMatch]:
    city_config = resolve_city(city)
    require_mocks()
    return mocks.mock_search(city_config.code, q)


@router.post("/report")
def report(request: ReportRequest) -> LocationReport:
    city_config = resolve_city(request.city)
    resolve_niche(request.niche)
    require_mocks()
    try:
        return mocks.mock_report(city_config, request)
    except mocks.PointOutsideCityError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


app = FastAPI(title="ГеоСтарт API", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=cors_origins(), allow_methods=["GET", "POST"], allow_headers=["*"]
)
app.include_router(router)
