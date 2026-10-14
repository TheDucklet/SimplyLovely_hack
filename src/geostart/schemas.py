from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high"]
DataSource = Literal["osm", "mos_ru"]
ServiceMode = Literal["mocks", "data"]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    mode: ServiceMode
    data_version: str


class CityInfo(BaseModel):
    code: str
    name: str
    center: tuple[float, float]
    zoom: int


class NicheInfo(BaseModel):
    code: str
    name: str


class HexScore(BaseModel):
    h3: str
    revenue_p50: float
    payback_months_p50: float | None
    risk_level: RiskLevel
    competitors_500m: int


class HexesResponse(BaseModel):
    city: str
    niche: str
    data_version: str
    items: list[HexScore]


class Competitor(BaseModel):
    name: str
    brand: str | None
    lat: float
    lon: float
    source: DataSource


class AddressMatch(BaseModel):
    address: str
    lat: float
    lon: float


class ReportRequest(BaseModel):
    city: str
    niche: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    area_m2: float | None = Field(default=None, gt=0)
    rent_rub_m2_month: float | None = Field(default=None, gt=0)


class ReportLocation(BaseModel):
    lat: float
    lon: float
    h3: str
    address: str | None


class MoneyRange(BaseModel):
    p10: float
    p50: float
    p90: float


class MonthlyCosts(BaseModel):
    rent: float
    payroll: float
    cogs: float
    taxes: float
    other: float
    total: float


class Factor(BaseModel):
    code: str
    name: str
    value: float
    unit: str
    effect_rub: float


class NearbyCompetitor(BaseModel):
    name: str
    lat: float
    lon: float
    distance_m: float


class Assumption(BaseModel):
    name: str
    value: float | str
    unit: str
    source: str | None


class LocationReport(BaseModel):
    city: str
    niche: str
    location: ReportLocation
    revenue_month: MoneyRange
    costs_month: MonthlyCosts
    profit_month_p50: float
    capex_rub_p50: float
    payback_months_p50: float | None
    risk_level: RiskLevel
    factors: list[Factor]
    competitors: list[NearbyCompetitor]
    assumptions: list[Assumption]
    data_version: str
