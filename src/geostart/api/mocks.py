from dataclasses import dataclass
from functools import cache
from math import asin, cos, radians, sin, sqrt

import h3
import pandas as pd

from geostart.config import CityConfig
from geostart.pipeline.fixtures import build_addresses, build_competitors, build_hex_features
from geostart.schemas import (
    AddressMatch,
    Assumption,
    Competitor,
    Factor,
    HexesResponse,
    HexScore,
    LocationReport,
    MoneyRange,
    MonthlyCosts,
    NearbyCompetitor,
    ReportLocation,
    ReportRequest,
    RiskLevel,
)

MOCK_DATA_VERSION = "2026-10-15-mock"
COMPETITION_RING = 3
SEARCH_LIMIT = 10
NEARBY_COMPETITORS_LIMIT = 5
FACTORS_LIMIT = 5
EARTH_RADIUS_M = 6_371_000
P10_SHARE_OF_P50 = 0.75
P90_SHARE_OF_P50 = 1.28
HIGH_RISK_MARGIN = 0.0
LOW_RISK_MARGIN = 0.15
SCOPE_PHRASES = {"inside_mkad": "внутри МКАД", "city_boundary": "в границах города"}


@dataclass(frozen=True)
class NicheEconomics:
    base_revenue: float
    revenue_per_resident: float
    revenue_per_worker: float
    loss_per_competitor: float
    min_revenue: float
    max_revenue: float
    default_area_m2: float
    staff_count: int
    wage_rub: dict[str, float]
    cogs_share: float
    other_opex_rub: float
    capex_rub: float
    tax_share: float


NICHE_ECONOMICS = {
    "coffee": NicheEconomics(
        base_revenue=300_000,
        revenue_per_resident=230,
        revenue_per_worker=200,
        loss_per_competitor=12_000,
        min_revenue=120_000,
        max_revenue=2_500_000,
        default_area_m2=40,
        staff_count=3,
        wage_rub={"moscow": 72_000, "tula": 42_000},
        cogs_share=0.30,
        other_opex_rub=60_000,
        capex_rub=3_000_000,
        tax_share=0.06,
    ),
    "pickup_point": NicheEconomics(
        base_revenue=90_000,
        revenue_per_resident=110,
        revenue_per_worker=15,
        loss_per_competitor=5_000,
        min_revenue=30_000,
        max_revenue=900_000,
        default_area_m2=30,
        staff_count=1,
        wage_rub={"moscow": 65_000, "tula": 40_000},
        cogs_share=0.0,
        other_opex_rub=30_000,
        capex_rub=1_200_000,
        tax_share=0.06,
    ),
}
MOCK_RENT_RUB_M2 = {"moscow": 3_500, "tula": 1_200}
PAYROLL_CONTRIBUTIONS_SHARE = 0.30
FACTOR_LABELS = {
    "residents": ("Жители в ячейке", "чел."),
    "workers": ("Работающие в ячейке", "чел."),
    "competitors_500m": ("Конкуренты в радиусе 500 м", "шт."),
}


def competitors_by_cell(city_code: str, niche_code: str) -> dict[str, int]:
    competitors = build_competitors(city_code)
    counts = competitors.loc[competitors["niche"] == niche_code, "h3"].value_counts()
    return counts.to_dict()


@cache
def competitors_500m(city_code: str, niche_code: str) -> dict[str, int]:
    per_cell = competitors_by_cell(city_code, niche_code)
    cells = build_hex_features(city_code)["h3"]
    return {
        cell: sum(per_cell.get(neighbor, 0) for neighbor in h3.grid_disk(cell, COMPETITION_RING))
        for cell in cells
    }


def revenue_p50(niche_code: str, residents: float, workers: float, competitors: int) -> float:
    economics = NICHE_ECONOMICS[niche_code]
    revenue = (
        economics.base_revenue
        + economics.revenue_per_resident * residents
        + economics.revenue_per_worker * workers
        - economics.loss_per_competitor * competitors
    )
    return float(min(max(revenue, economics.min_revenue), economics.max_revenue))


def monthly_costs(
    city_code: str, niche_code: str, revenue: float, area_m2: float, rent_rub_m2: float
) -> MonthlyCosts:
    economics = NICHE_ECONOMICS[niche_code]
    rent = area_m2 * rent_rub_m2
    payroll = economics.staff_count * economics.wage_rub[city_code] * (1 + PAYROLL_CONTRIBUTIONS_SHARE)
    cogs = economics.cogs_share * revenue
    taxes = economics.tax_share * revenue
    other = economics.other_opex_rub
    return MonthlyCosts(
        rent=round(rent),
        payroll=round(payroll),
        cogs=round(cogs),
        taxes=round(taxes),
        other=round(other),
        total=round(rent + payroll + cogs + taxes + other),
    )


def risk_level(profit: float, revenue: float) -> RiskLevel:
    margin = profit / revenue if revenue else -1.0
    if margin <= HIGH_RISK_MARGIN:
        return "high"
    if margin < LOW_RISK_MARGIN:
        return "medium"
    return "low"


def payback_months(niche_code: str, profit: float) -> float | None:
    if profit <= 0:
        return None
    return round(NICHE_ECONOMICS[niche_code].capex_rub / profit, 1)


@cache
def mock_hexes(city_code: str, niche_code: str) -> HexesResponse:
    features = build_hex_features(city_code)
    competition = competitors_500m(city_code, niche_code)
    default_area = NICHE_ECONOMICS[niche_code].default_area_m2
    items = []
    for row in features.itertuples(index=False):
        competitors = competition[row.h3]
        revenue = revenue_p50(niche_code, row.residents, row.workers, competitors)
        costs = monthly_costs(city_code, niche_code, revenue, default_area, MOCK_RENT_RUB_M2[city_code])
        profit = revenue - costs.total
        items.append(
            HexScore(
                h3=row.h3,
                revenue_p50=round(revenue),
                payback_months_p50=payback_months(niche_code, profit),
                risk_level=risk_level(profit, revenue),
                competitors_500m=competitors,
            )
        )
    return HexesResponse(city=city_code, niche=niche_code, data_version=MOCK_DATA_VERSION, items=items)


def mock_competitors(city_code: str, niche_code: str) -> list[Competitor]:
    competitors = build_competitors(city_code)
    selected = competitors[competitors["niche"] == niche_code]
    return [
        Competitor(
            name=row.name,
            brand=None if pd.isna(row.brand) else row.brand,
            lat=row.lat,
            lon=row.lon,
            source=row.source,
        )
        for row in selected.itertuples(index=False)
    ]


def mock_search(city_code: str, query: str) -> list[AddressMatch]:
    addresses = build_addresses(city_code)
    matches = addresses[addresses["address"].str.contains(query.strip(), case=False, regex=False)]
    return [
        AddressMatch(address=row.address, lat=row.lat, lon=row.lon)
        for row in matches.head(SEARCH_LIMIT).itertuples(index=False)
    ]


class PointOutsideCityError(ValueError):
    pass


def distance_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    delta_lat = radians(lat_b - lat_a)
    delta_lon = radians(lon_b - lon_a)
    chord = sin(delta_lat / 2) ** 2 + cos(radians(lat_a)) * cos(radians(lat_b)) * sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(chord))


def nearest_address(city_code: str, cell: str, lat: float, lon: float) -> str | None:
    addresses = build_addresses(city_code)
    in_cell = addresses[addresses["h3"] == cell]
    if in_cell.empty:
        return None
    distances = in_cell.apply(lambda row: distance_m(lat, lon, row["lat"], row["lon"]), axis=1)
    return str(in_cell.loc[distances.idxmin(), "address"])


def nearby_competitors(
    city_code: str, niche_code: str, cell: str, lat: float, lon: float
) -> list[NearbyCompetitor]:
    competitors = build_competitors(city_code)
    disk = h3.grid_disk(cell, COMPETITION_RING)
    nearby = competitors[(competitors["niche"] == niche_code) & competitors["h3"].isin(disk)]
    result = [
        NearbyCompetitor(
            name=row.name, lat=row.lat, lon=row.lon, distance_m=round(distance_m(lat, lon, row.lat, row.lon))
        )
        for row in nearby.itertuples(index=False)
    ]
    return sorted(result, key=lambda competitor: competitor.distance_m)[:NEARBY_COMPETITORS_LIMIT]


def report_factors(
    niche_code: str,
    cell_row: pd.Series,
    features: pd.DataFrame,
    competitors: int,
    city_median_competitors: float,
) -> list[Factor]:
    values = {
        "residents": float(cell_row["residents"]),
        "workers": float(cell_row["workers"]),
        "competitors_500m": float(competitors),
    }
    medians = {
        "residents": float(features["residents"].median()),
        "workers": float(features["workers"].median()),
        "competitors_500m": city_median_competitors,
    }
    actual = revenue_p50(niche_code, values["residents"], values["workers"], int(values["competitors_500m"]))
    factors = []
    for code, (name, unit) in FACTOR_LABELS.items():
        replaced = {**values, code: medians[code]}
        baseline = revenue_p50(
            niche_code, replaced["residents"], replaced["workers"], round(replaced["competitors_500m"])
        )
        factors.append(
            Factor(
                code=code,
                name=name,
                value=round(values[code], 1),
                unit=unit,
                effect_rub=round(actual - baseline),
            )
        )
    return sorted(factors, key=lambda factor: abs(factor.effect_rub), reverse=True)[:FACTORS_LIMIT]


def mock_report(city: CityConfig, request: ReportRequest) -> LocationReport:
    features = build_hex_features(city.code)
    cell = h3.latlng_to_cell(request.lat, request.lon, city.h3_resolution)
    matched = features[features["h3"] == cell]
    if matched.empty:
        raise PointOutsideCityError(
            f"Точка вне границ города {city.code}, выберите место {SCOPE_PHRASES[city.scope]}"
        )
    cell_row = matched.iloc[0]
    competition = competitors_500m(city.code, request.niche)
    competitors = competition[cell]
    economics = NICHE_ECONOMICS[request.niche]
    area = request.area_m2 or economics.default_area_m2
    rent_rate = request.rent_rub_m2_month or MOCK_RENT_RUB_M2[city.code]
    revenue = revenue_p50(request.niche, cell_row["residents"], cell_row["workers"], competitors)
    costs = monthly_costs(city.code, request.niche, revenue, area, rent_rate)
    profit = revenue - costs.total
    median_competitors = float(pd.Series(list(competition.values())).median())
    return LocationReport(
        city=city.code,
        niche=request.niche,
        location=ReportLocation(
            lat=request.lat,
            lon=request.lon,
            h3=cell,
            address=nearest_address(city.code, cell, request.lat, request.lon),
        ),
        revenue_month=MoneyRange(
            p10=round(revenue * P10_SHARE_OF_P50), p50=round(revenue), p90=round(revenue * P90_SHARE_OF_P50)
        ),
        costs_month=costs,
        profit_month_p50=round(profit),
        capex_rub_p50=economics.capex_rub,
        payback_months_p50=payback_months(request.niche, profit),
        risk_level=risk_level(profit, revenue),
        factors=report_factors(request.niche, cell_row, features, competitors, median_competitors),
        competitors=nearby_competitors(city.code, request.niche, cell, request.lat, request.lon),
        assumptions=[
            Assumption(name="Площадь помещения", value=area, unit="м²", source=None),
            Assumption(name="Ставка аренды", value=rent_rate, unit="₽/м² в месяц", source=None),
            Assumption(
                name="Режим данных", value="синтетические данные для разработки", unit="", source=None
            ),
        ],
        data_version=MOCK_DATA_VERSION,
    )
