import time

from geostart.economics.service import evaluate_economics
from geostart.schemas_v2 import EconomicsRequest

CASES = (
    ("Москва", "moscow", "coffee", "кофейня", 55.7605, 37.6191),
    ("Тула", "tula", "coffee", "кофейня", 54.193, 37.617),
    ("Новосибирск", "novosibirsk", "grocery", "продукты у дома", 55.0302, 82.9204),
    ("Санкт-Петербург", "saint_petersburg", "bakery", "пекарня", 59.9343, 30.3351),
    ("Екатеринбург", "yekaterinburg", "flowers", "цветы", 56.8389, 60.6057),
)
SOURCES = ("geostart", "geoplatform")


def thousands(value: float | None) -> str:
    return "–" if value is None else f"{round(value / 1000) + 0:,}".replace(",", " ")


def months(value: float | None) -> str:
    return "не окупается" if value is None else f"{value:.1f}".replace(".", ",")


def main() -> None:
    print(
        "| Город | Ниша | Источник | Выручка p50, тыс. ₽ | Прибыль месяца p50, тыс. ₽ "
        "| Окупаемость p50, мес. | NPV p50, тыс. ₽ | Время, с |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for city_name, city, niche, niche_name, lat, lon in CASES:
        for source in SOURCES:
            request = EconomicsRequest(
                city=city,
                niche=niche,
                demand={"source": source, "lat": lat, "lon": lon},
                start_year=2027,
                start_month=1,
            )
            started = time.perf_counter()
            report = evaluate_economics(request)
            elapsed = time.perf_counter() - started
            cells = [
                city_name,
                niche_name,
                "модель ГеоСтарт" if source == "geostart" else "заглушка геоплатформы",
                thousands(report.demand.revenue_steady_month.p50),
                thousands(report.metrics.profit_steady_month.p50),
                months(report.metrics.payback_months.p50),
                thousands(report.metrics.npv.p50),
                f"{elapsed:.1f}".replace(".", ","),
            ]
            print("| " + " | ".join(cells) + " |", flush=True)


if __name__ == "__main__":
    main()
