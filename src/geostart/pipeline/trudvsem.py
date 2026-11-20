import json
import logging
import statistics
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from geostart.pipeline.fixtures import WAGE_COLUMNS

logger = logging.getLogger(__name__)

TRUDVSEM_URL = "http://opendata.trudvsem.ru/api/v1/vacancies/region/{region}"
PROFESSION_QUERIES = {
    "barista": ["бариста"],
    "pickup_operator": ["оператор пункта выдачи", "менеджер пункта выдачи"],
    "grocery_seller": ["продавец-кассир", "продавец продовольственных товаров"],
    "hairdresser": ["парикмахер", "мастер маникюра"],
    "fast_food_cook": ["повар-кассир", "повар быстрого питания"],
    "baker": ["пекарь", "пекарь-кондитер"],
    "florist": ["флорист"],
}
PROXY_QUERIES = {
    "barista": ["официант"],
    "pickup_operator": ["кассир"],
    "grocery_seller": ["кассир"],
    "hairdresser": ["мастер ногтевого сервиса", "косметолог"],
    "fast_food_cook": ["повар"],
    "baker": ["повар"],
    "florist": ["продавец"],
}
MIN_VACANCIES_WITH_SALARY = 4
CACHED_VACANCY_FIELDS = ("id", "job-name", "salary_min", "salary_max", "creation-date")
PAGE_SIZE = 100
MAX_PAGES = 20
REQUEST_TIMEOUT_SECONDS = 120
REQUEST_ATTEMPTS = 4
RETRY_PAUSE_SECONDS = 10
RECENT_VACANCY_DAYS = 365
MIN_PLAUSIBLE_SALARY_RUB = 15_000
MAX_PLAUSIBLE_SALARY_RUB = 500_000


def fetch_page(region: str, query: str, page: int) -> dict:
    for attempt in range(1, REQUEST_ATTEMPTS + 1):
        try:
            response = requests.get(
                TRUDVSEM_URL.format(region=region),
                params={"text": query, "limit": PAGE_SIZE, "offset": page},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError):
            if attempt == REQUEST_ATTEMPTS:
                raise
            logger.warning("Работа России не ответила на запрос «%s», повтор %d", query, attempt)
            time.sleep(RETRY_PAUSE_SECONDS * attempt)
    return {}


def fetch_vacancies(region: str, query: str) -> list[dict]:
    vacancies = []
    for page in range(MAX_PAGES):
        batch = fetch_page(region, query, page).get("results", {}).get("vacancies", [])
        vacancies.extend(item["vacancy"] for item in batch)
        if len(batch) < PAGE_SIZE:
            break
    return vacancies


def vacancy_salary(vacancy: dict) -> float | None:
    bounds = [value for value in (vacancy.get("salary_min"), vacancy.get("salary_max")) if value]
    if not bounds:
        return None
    salary = sum(bounds) / len(bounds)
    if not MIN_PLAUSIBLE_SALARY_RUB <= salary <= MAX_PLAUSIBLE_SALARY_RUB:
        return None
    return salary


def is_recent(vacancy: dict, collected_at: date) -> bool:
    created = vacancy.get("creation-date")
    if not created:
        return False
    return date.fromisoformat(created[:10]) >= collected_at - timedelta(days=RECENT_VACANCY_DAYS)


def minimize_vacancy(vacancy: dict) -> dict:
    return {field: vacancy.get(field) for field in CACHED_VACANCY_FIELDS}


def write_cache(cache_path: Path, vacancies: list[dict]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(vacancies, ensure_ascii=False), encoding="utf-8")


def load_vacancies(region: str, cache_name: str, queries: list[str], cache_dir: Path) -> list[dict]:
    cache_path = cache_dir / f"{region}_{cache_name}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        minimized = [minimize_vacancy(vacancy) for vacancy in cached]
        if minimized != cached:
            write_cache(cache_path, minimized)
        return minimized
    vacancies: dict[str, dict] = {}
    for query in queries:
        for vacancy in fetch_vacancies(region, query):
            vacancies[vacancy["id"]] = minimize_vacancy(vacancy)
    write_cache(cache_path, list(vacancies.values()))
    return list(vacancies.values())


def recent_salaries(vacancies: list[dict], collected_at: date) -> list[float]:
    return sorted(
        salary
        for vacancy in vacancies
        if is_recent(vacancy, collected_at) and (salary := vacancy_salary(vacancy)) is not None
    )


def wage_row(profession: str, salaries: list[float], basis: str, collected_at: date) -> dict:
    quartiles = statistics.quantiles(salaries, n=4)
    return {
        "profession": profession,
        "salary_p25": round(quartiles[0]),
        "salary_p50": round(quartiles[1]),
        "salary_p75": round(quartiles[2]),
        "vacancies_n": len(salaries),
        "collected_at": pd.Timestamp(collected_at),
        "basis": basis,
    }


def build_wages(region: str, cache_dir: Path, collected_at: date) -> pd.DataFrame:
    rows = []
    for profession, queries in PROFESSION_QUERIES.items():
        salaries = recent_salaries(load_vacancies(region, profession, queries, cache_dir), collected_at)
        if len(salaries) >= MIN_VACANCIES_WITH_SALARY:
            rows.append(wage_row(profession, salaries, "direct", collected_at))
            continue
        proxy_queries = PROXY_QUERIES[profession]
        proxy_salaries = recent_salaries(
            load_vacancies(region, f"{profession}_proxy", proxy_queries, cache_dir), collected_at
        )
        if len(proxy_salaries) < MIN_VACANCIES_WITH_SALARY:
            logger.warning("Для профессии %s в регионе %s нет данных о зарплатах", profession, region)
            continue
        logger.warning(
            "Для профессии %s в регионе %s использованы вакансии «%s»",
            profession,
            region,
            ", ".join(proxy_queries),
        )
        rows.append(wage_row(profession, proxy_salaries, "proxy", collected_at))
    return pd.DataFrame(rows, columns=WAGE_COLUMNS)
