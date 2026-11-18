import time

from geostart.api.data_backend import data_search
from geostart.economics.service import evaluate_economics
from geostart.schemas_v2 import EconomicsRequest

ADDRESSES = {"moscow": "Тверская улица, 7", "tula": "Советская улица, 1"}
NICHES = ("coffee", "pickup_point")
NICHE_NAMES = {"coffee": "кофейня", "pickup_point": "пункт выдачи"}
CITY_NAMES = {"moscow": "Москва", "tula": "Тула"}
VARIANTS = {"исследование": {}, "60 м² по 1500 ₽": {"area_m2": 60, "rent_rub_m2_month": 1500}}
START_YEAR = 2027
START_MONTH = 1


def thousands(value: float | None) -> str:
    return "–" if value is None else f"{round(value / 1000) + 0:,}".replace(",", " ")


def months(value: float | None) -> str:
    return "не окупается" if value is None else f"{value:.1f}".replace(".", ",")


def row(city: str, niche: str, variant: str, premises: dict) -> str:
    match = data_search(city, ADDRESSES[city])[0]
    request = EconomicsRequest(
        city=city,
        niche=niche,
        demand={"source": "geostart", "lat": match.lat, "lon": match.lon},
        premises=premises,
        start_month=START_MONTH,
        start_year=START_YEAR,
    )
    started = time.perf_counter()
    report = evaluate_economics(request)
    elapsed = time.perf_counter() - started
    metrics = report.metrics
    cells = [
        f"{CITY_NAMES[city]}, {NICHE_NAMES[niche]}, {ADDRESSES[city]}",
        variant,
        thousands(report.demand.revenue_steady_month.p50),
        thousands(report.investment.total.p50),
        report.tax.name,
        thousands(metrics.profit_steady_month.p50),
        months(metrics.payback_months.p50),
        f"{metrics.probability_no_payback * 100:.0f}%",
        thousands(metrics.npv.p50),
        months(metrics.break_even_units_per_day.p50).replace("не окупается", "–"),
        thousands(report.credit.max_loan_rub.p50),
        f"{elapsed:.1f}".replace(".", ","),
    ]
    return "| " + " | ".join(cells) + " |"


def main() -> None:
    print(
        "| Точка | Вариант | Выручка p50, тыс. ₽ | Вложения p50, тыс. ₽ | Режим | Прибыль месяца p50, тыс. ₽ "
        "| Окупаемость p50, мес. | Не окупается | NPV p50, тыс. ₽ | Безубыточность, ед. в день "
        "| Предельный кредит p50, тыс. ₽ | Время, с |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for city in ADDRESSES:
        for niche in NICHES:
            for variant, premises in VARIANTS.items():
                print(row(city, niche, variant, premises), flush=True)


if __name__ == "__main__":
    main()
