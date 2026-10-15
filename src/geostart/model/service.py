import json
from dataclasses import dataclass
from math import ceil
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import yaml
from shapely.geometry import Point, shape
from shapely.ops import unary_union

from geostart import settings
from geostart.config import get_city, get_niche
from geostart.model.assumptions import PARAMETER_NAMES, demand_assumptions, resolve_rent, wage_assumptions
from geostart.model.data import city_directory, scores_directory
from geostart.model.demand import (
    DEFAULT_SEED,
    GRID_EDGE_SAFETY_FACTOR,
    GRID_RADIUS_MARGIN,
    QUANTILES,
    DemandModel,
    distances_m,
    prepare_model,
    sample_parameters,
)
from geostart.model.factors import COMPETITOR_RADIUS_M, explain_factors
from geostart.model.finance import (
    MONTHS_PER_YEAR,
    FinanceResult,
    calculate_finance,
    payback_months,
    risk_levels,
    sample_finance_parameters,
)
from geostart.schemas import (
    Assumption,
    LocationReport,
    MoneyRange,
    MonthlyCosts,
    NearbyCompetitor,
    ReportLocation,
)

ASSUMPTION_NAMES = {
    "area_m2": ("Площадь помещения", "м²"),
    "staff_count": ("Число сотрудников", "чел."),
    "cogs_share_of_revenue": ("Доля себестоимости", "доля"),
    "other_opex_rub": ("Прочие расходы", "₽/месяц"),
    "capex_rub": ("Капитальные затраты", "₽"),
}
TAX_NAMES = {
    "usn_income_rate": "Ставка УСН с доходов",
    "usn_income_minus_expenses_rate": "Ставка УСН с разницы",
    "employer_contributions_rate": "Взносы работодателя",
    "vat_threshold_usn_rub_year": "Порог НДС исследования",
    "moscow_trade_fee_rub_quarter": "Торговый сбор исследования",
}


@dataclass(frozen=True)
class CityInputs:
    directory: Path
    features: pd.DataFrame
    competitors: pd.DataFrame
    wages: pd.DataFrame
    rents: pd.DataFrame
    parameters: dict
    taxes: dict
    salary: float
    data_version: str


def load_inputs(city: str, niche: str) -> CityInputs:
    get_city(city)
    get_niche(niche)
    directory = city_directory(city)
    root = settings.research_dir()
    with (root / "niche_params" / f"{niche}.yaml").open(encoding="utf-8") as stream:
        parameters = yaml.safe_load(stream)
    with (root / "taxes" / "2026.yaml").open(encoding="utf-8") as stream:
        taxes = yaml.safe_load(stream)
    features = pd.read_parquet(directory / "hex_features.parquet")
    competitors = pd.read_parquet(directory / "competitors.parquet")
    wages = pd.read_parquet(directory / "wages.parquet")
    profession = parameters["costs"]["wage_profession"]
    salaries = wages.loc[wages["profession"].eq(profession), "salary_p50"]
    if salaries.empty:
        raise ValueError(f"Нет зарплаты профессии {profession}, загрузите данные вакансий")
    return CityInputs(
        directory,
        features,
        competitors,
        wages,
        pd.read_csv(root / "rent" / f"{city}.csv"),
        parameters,
        taxes,
        float(salaries.median()),
        pd.to_datetime(wages["collected_at"]).max().date().isoformat(),
    )


def rent_rates(inputs: CityInputs, features: pd.DataFrame) -> np.ndarray:
    rates = {district: resolve_rent(inputs.rents, district)[0] for district in features["district"].unique()}
    return features["district"].map(rates).to_numpy(dtype=float)


def run_simulation(
    inputs: CityInputs,
    model: DemandModel,
    samples: pd.DataFrame,
    area_m2: float | None = None,
    rent_rub_m2_month: float | None = None,
) -> tuple[np.ndarray, FinanceResult]:
    revenues = np.array([model.revenue(parameters) for parameters in samples.to_dict("records")])
    finance_samples = sample_finance_parameters(inputs.parameters, len(samples), DEFAULT_SEED)
    if area_m2 is not None:
        finance_samples["area_m2"] = area_m2
    rates = rent_rates(inputs, model.features)
    if rent_rub_m2_month is not None:
        rates = np.full(len(model.features), rent_rub_m2_month)
    finance = calculate_finance(
        revenues,
        finance_samples,
        rates,
        inputs.salary,
        inputs.parameters["tax_regime_default"],
        inputs.taxes,
    )
    return revenues, finance


def nearby_indices(features: pd.DataFrame, competitors: pd.DataFrame, niche: str) -> list[np.ndarray]:
    selected = competitors.loc[competitors["niche"].eq(niche)].reset_index(drop=True)
    coordinates = selected[["lat", "lon"]].to_numpy(dtype=float)
    groups = selected.groupby("h3", sort=False).indices
    resolution = h3.get_resolution(features.iloc[0]["h3"])
    radius = (
        ceil(
            COMPETITOR_RADIUS_M
            / (h3.average_hexagon_edge_length(resolution, unit="m") * GRID_EDGE_SAFETY_FACTOR)
        )
        + GRID_RADIUS_MARGIN
    )
    result = []
    for cell in features["h3"]:
        candidates = [groups[neighbor] for neighbor in h3.grid_disk(cell, radius) if neighbor in groups]
        indices = np.concatenate(candidates) if candidates else np.array([], dtype=int)
        center = np.array(h3.cell_to_latlng(cell))
        distances = distances_m(np.tile(center, (len(indices), 1)), coordinates[indices])
        result.append(indices[distances <= COMPETITOR_RADIUS_M])
    return result


def score_city(city: str, niche: str) -> pd.DataFrame:
    inputs = load_inputs(city, niche)
    samples = sample_parameters(niche, inputs.parameters["demand"])
    model = prepare_model(
        inputs.features, inputs.competitors, niche, float(samples.max_walk_distance_m.max())
    )
    revenues, finance = run_simulation(inputs, model, samples)
    quantiles = np.quantile(revenues, QUANTILES, axis=0)
    profit_p50 = np.median(finance.profits, axis=0)
    capex_p50 = np.median(finance.capex, axis=0)
    counts = [len(indices) for indices in nearby_indices(inputs.features, inputs.competitors, niche)]
    scores = pd.DataFrame(
        {
            "h3": inputs.features["h3"].to_numpy(),
            "revenue_p10": quantiles[0],
            "revenue_p50": quantiles[1],
            "revenue_p90": quantiles[2],
            "profit_p50": profit_p50,
            "payback_months_p50": payback_months(capex_p50, profit_p50),
            "risk_level": risk_levels(finance.profits),
            "competitors_500m": counts,
        }
    )
    directory = scores_directory()
    directory.mkdir(parents=True, exist_ok=True)
    scores.to_parquet(directory / f"{city}_{niche}.parquet", index=False)
    return scores


def validate_location(inputs: CityInputs, lat: float, lon: float, city: str) -> None:
    if not np.isfinite([lat, lon]).all() or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Координаты должны быть конечными и в допустимом диапазоне")
    with (inputs.directory / "boundary.geojson").open(encoding="utf-8") as stream:
        boundary = json.load(stream)
    if boundary["type"] == "FeatureCollection":
        geometry = unary_union([shape(feature["geometry"]) for feature in boundary["features"]])
    elif boundary["type"] == "Feature":
        geometry = shape(boundary["geometry"])
    else:
        geometry = shape(boundary)
    if not geometry.covers(Point(lon, lat)):
        raise ValueError(f"Точка вне границ города {city}, выберите место внутри границы")


def local_features(inputs: CityInputs, cell: str, radius_m: float) -> tuple[pd.DataFrame, int]:
    coordinates = np.array([h3.cell_to_latlng(item) for item in inputs.features["h3"]])
    center = np.array(h3.cell_to_latlng(cell))
    distances = distances_m(np.tile(center, (len(coordinates), 1)), coordinates)
    features = inputs.features.loc[distances <= radius_m].copy().reset_index(drop=True)
    if cell not in set(features["h3"]):
        empty = {column: 0 for column in inputs.features.columns}
        empty.update(h3=cell, lat=center[0], lon=center[1], district="Без ставки района", metro_dist_m=np.nan)
        features = pd.concat([features, pd.DataFrame([empty])], ignore_index=True)
    candidate_index = int(np.flatnonzero(features["h3"].eq(cell))[0])
    return features, candidate_index


def report_assumptions(inputs: CityInputs, district: str, revenue_p50: float, city: str) -> list[Assumption]:
    parameters = inputs.parameters
    assumptions = demand_assumptions(parameters)
    for name, bounds in parameters["demand"].items():
        if bounds.get("source"):
            assumptions.append(
                Assumption(
                    name=PARAMETER_NAMES.get(name, name),
                    value=float(bounds["p50"]),
                    unit="",
                    source=bounds["source"],
                )
            )
    for code, (name, unit) in ASSUMPTION_NAMES.items():
        bounds = parameters["capex_rub"] if code == "capex_rub" else parameters["costs"][code]
        explanation = "" if bounds.get("source") else " – условное значение без подтверждённого источника"
        assumptions.append(
            Assumption(
                name=name + explanation, value=float(bounds["p50"]), unit=unit, source=bounds.get("source")
            )
        )
    for code, name in TAX_NAMES.items():
        bounds = inputs.taxes[code]
        if code == "moscow_trade_fee_rub_quarter" and not bounds["applies_to"]:
            continue
        explanation = (
            " – условное значение исследования" if inputs.taxes.get("status") == "placeholder" else ""
        )
        assumptions.append(
            Assumption(
                name=name + explanation,
                value=bounds["value"],
                unit=bounds["unit"],
                source=bounds.get("source"),
            )
        )
    assumptions.extend(wage_assumptions(inputs.wages, parameters["costs"]["wage_profession"]))
    assumptions.append(
        Assumption(
            name="Медианная зарплата используемой профессии",
            value=inputs.salary,
            unit="₽/месяц",
            source="https://opendata.trudvsem.ru",
        )
    )
    _, fallback = resolve_rent(inputs.rents, district)
    assumptions.extend(fallback)
    rent_rows = inputs.rents.loc[inputs.rents["zone"].eq(district)]
    if not rent_rows.empty:
        row = rent_rows.iloc[0]
        assumptions.append(
            Assumption(
                name="Ставка аренды района",
                value=float(row.rent_rub_m2_month_p50),
                unit="₽/м² в месяц",
                source=None if pd.isna(row.source) else row.source,
            )
        )
    if inputs.rents["date"].eq("placeholder").any():
        assumptions.append(
            Assumption(name="Ставки аренды", value="Условные значения до исследования", unit="", source=None)
        )
    if revenue_p50 * MONTHS_PER_YEAR > float(inputs.taxes["vat_threshold_usn_rub_year"]["value"]):
        assumptions.append(
            Assumption(
                name="Предупреждение о НДС",
                value="Годовая выручка выше порога исследования, расходы НДС не рассчитаны",
                unit="",
                source=inputs.taxes["vat_threshold_usn_rub_year"].get("source"),
            )
        )
    if city == "tula" and parameters["niche"] == "coffee":
        assumptions.append(
            Assumption(
                name="Неполная разметка кофеен OSM",
                value="В Туле известно 38 кофеен, конкуренция занижена источником",
                unit="",
                source=None,
            )
        )
    assumptions.append(
        Assumption(
            name="Границы финансового расчёта",
            value="Постоянный месяц, взносы ИП и сезонность не учтены, НДС только предупреждается",
            unit="",
            source=None,
        )
    )
    return assumptions


def evaluate_location(
    city: str,
    niche: str,
    lat: float,
    lon: float,
    area_m2: float | None = None,
    rent_rub_m2_month: float | None = None,
) -> LocationReport:
    for name, value in (("Площадь", area_m2), ("Аренда", rent_rub_m2_month)):
        if value is not None and (not np.isfinite(value) or value <= 0):
            raise ValueError(f"{name} должна быть положительной и конечной")
    inputs = load_inputs(city, niche)
    validate_location(inputs, lat, lon, city)
    cell = h3.latlng_to_cell(lat, lon, get_city(city).h3_resolution)
    samples = sample_parameters(niche, inputs.parameters["demand"])
    radius_m = float(samples.max_walk_distance_m.max())
    features, candidate_index = local_features(inputs, cell, radius_m)
    model = prepare_model(features, inputs.competitors, niche, radius_m)
    revenues, finance = run_simulation(inputs, model, samples, area_m2, rent_rub_m2_month)
    quantiles = np.quantile(revenues[:, candidate_index], QUANTILES)
    profit_p50 = float(np.median(finance.profits[:, candidate_index]))
    capex_p50 = float(np.median(finance.capex[:, candidate_index]))
    components = {
        name: float(np.median(getattr(finance, name)[:, candidate_index]))
        for name in ("rent", "payroll", "cogs", "taxes", "other")
    }
    components["total"] = sum(components.values())
    selected = inputs.competitors.loc[inputs.competitors["niche"].eq(niche)].reset_index(drop=True)
    nearby = nearby_indices(features.iloc[[candidate_index]], inputs.competitors, niche)[0]
    center = np.array(h3.cell_to_latlng(cell))
    point_coordinates = selected.iloc[nearby][["lat", "lon"]].to_numpy(dtype=float)
    point_distances = distances_m(np.tile(center, (len(nearby), 1)), point_coordinates)
    competitor_reports = [
        NearbyCompetitor(
            name=str(row["name"] or "Без названия"),
            lat=row["lat"],
            lon=row["lon"],
            distance_m=float(distance),
        )
        for (_, row), distance in zip(selected.iloc[nearby].iterrows(), point_distances, strict=True)
    ]
    competitor_reports.sort(key=lambda competitor: competitor.distance_m)
    city_counts = np.array(
        [len(indices) for indices in nearby_indices(inputs.features, inputs.competitors, niche)]
    )
    factors = explain_factors(
        model,
        candidate_index,
        inputs.features,
        inputs.competitors,
        city_counts,
        len(nearby),
        samples,
        float(quantiles[1]),
    )
    assumptions = report_assumptions(
        inputs, str(features.iloc[candidate_index].district), float(quantiles[1]), city
    )
    for name, value, unit in (
        ("Площадь пользователя", area_m2, "м²"),
        ("Ставка аренды пользователя", rent_rub_m2_month, "₽/м² в месяц"),
    ):
        if value is not None:
            assumptions.append(Assumption(name=name, value=value, unit=unit, source=None))
    if rent_rub_m2_month is not None:
        assumptions = [
            item
            for item in assumptions
            if not item.name.startswith(("Аренда района", "Ставка аренды района", "Ставки аренды"))
        ]
    if area_m2 is not None:
        assumptions = [item for item in assumptions if not item.name.startswith("Площадь помещения")]
    assumptions.append(
        Assumption(
            name="Расположение кандидата", value="Расчёт выполняется в центре ячейки H3", unit="", source=None
        )
    )
    if cell not in set(inputs.features["h3"]):
        assumptions.append(
            Assumption(
                name="Ячейка без признаков зданий",
                value="Собственные жители и рабочие места равны нулю, учитываются соседние ячейки",
                unit="",
                source=None,
            )
        )
    addresses = pd.read_parquet(inputs.directory / "addresses.parquet")
    matching = addresses.loc[addresses["h3"].eq(cell)]
    address = None
    if not matching.empty:
        distances = distances_m(np.tile([lat, lon], (len(matching), 1)), matching[["lat", "lon"]].to_numpy())
        address = str(matching.iloc[int(np.argmin(distances))].address)
    return LocationReport(
        city=city,
        niche=niche,
        location=ReportLocation(lat=lat, lon=lon, h3=cell, address=address),
        revenue_month=MoneyRange(p10=quantiles[0], p50=quantiles[1], p90=quantiles[2]),
        costs_month=MonthlyCosts(**components),
        profit_month_p50=profit_p50,
        capex_rub_p50=capex_p50,
        payback_months_p50=capex_p50 / profit_p50 if profit_p50 > 0 else None,
        risk_level=str(risk_levels(finance.profits)[candidate_index]),
        factors=factors,
        competitors=competitor_reports,
        assumptions=assumptions,
        data_version=inputs.data_version,
    )
