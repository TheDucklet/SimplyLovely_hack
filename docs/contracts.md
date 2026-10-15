# Контракты ГеоСтарта

Документ фиксирует структуру репозитория, форматы данных и интерфейсы между частями системы, чтобы участники могли работать параллельно с первого дня. Изменение контракта согласуется с Фёдором и вносится в `docs/contracts.md` репозитория отдельным коммитом. Значения в примерах условные.

## Технологии

| Часть | Выбор |
| --- | --- |
| Язык и окружение бэкенда | Python 3.13 (допускается 3.12, если путь к клону без кириллицы), менеджер пакетов uv |
| Качество кода Python | ruff (форматирование и линтер), pytest, аннотации типов |
| Хранение данных MVP | файлы Parquet, запросы через DuckDB или pandas |
| Геометрия и сетка | h3 версии 4, shapely, geopandas, pyrosm или osmium для OpenStreetMap |
| Модели данных и API | pydantic 2, FastAPI, uvicorn |
| Интерфейс | Node.js 20 LTS, Vite, React, TypeScript, MapLibre GL JS, deck.gl (`H3HexagonLayer`), h3-js 4 |
| Качество кода интерфейса | eslint, prettier |
| CI | GitHub Actions: ruff, pytest, сборка `web/` |

## Поток данных

Данные проходят путь от открытых источников до интерфейса через конвейер, модель и API, и каждый шаг принадлежит одному участнику.

Шаги обмениваются данными через файлы в `data/` и через HTTP, благодаря чему каждый шаг разрабатывается и тестируется отдельно на синтетических данных или заглушках.

## Структура репозитория

```
SimplyLovely_hack/
├── README.md
├── pyproject.toml
├── config/
│   ├── cities.yaml
│   └── niches.yaml
├── src/geostart/
│   ├── pipeline/
│   ├── model/
│   └── api/
├── web/
├── research/
│   ├── niche_params/
│   ├── rent/
│   └── taxes/
├── data/
├── tests/
└── docs/
    ├── architecture.md
    ├── contracts.md
    ├── data-sources.md
    ├── model.md
    ├── api.md
    └── decisions.md
```

| Каталог | Владелец | Содержание |
| --- | --- | --- |
| `src/geostart/pipeline/` | Фёдор | загрузка источников, сетка H3, признаки ячеек, генератор синтетических данных |
| `src/geostart/model/` | Роман | спрос, финансовый расчёт, факторы, расчёт по городу |
| `src/geostart/api/` | Фёдор | HTTP API |
| `web/` | Алексей | интерфейс |
| `research/` | Фёдор переносит материалы Ивана и Никиты | параметры ниш, аренда, налоги с источниками |
| `data/` | не хранится в git | `raw/`, `processed/<city>/`, `scores/` |

Каталог `data/` указан в `.gitignore`. Готовые данные Фёдор выкладывает архивом `geostart_data_<ГГГГ-ММ-ДД>.zip` на Яндекс.Диск команды, ссылка в README. До готовности реальных данных используется генератор синтетических данных. Команда `uv run python -m geostart.pipeline.fixtures --city all` создаёт файлы `data/processed/moscow/` и `data/processed/tula/` с правильными схемами, параметр `--city moscow` ограничивает генерацию одним городом.

## Конфигурация городов

`config/cities.yaml`:

```yaml
cities:
  - code: moscow
    name: Москва
    osm_boundary: Москва
    scope: inside_mkad
    h3_resolution: 9
    center: [55.7558, 37.6176]
    zoom: 11
  - code: tula
    name: Тула
    osm_boundary: городской округ Тула
    scope: city_boundary
    h3_resolution: 9
    center: [54.1931, 37.6173]
    zoom: 12
```

Новый город добавляется записью в этом файле и запуском конвейера, код при этом не меняется.

## Конфигурация ниш

`config/niches.yaml`:

```yaml
niches:
  - code: coffee
    name: Кофейня
    osm_tags:
      - {amenity: cafe, cuisine: coffee_shop}
      - {shop: coffee}
    osm_name_rules:
      - tags: {amenity: cafe}
        pattern: "(?i)коф|coffee|cofe|cofix|даблби|дринкит|шоколадница|кофемания"
    mos_ru_name_pattern: "(?i)коф|coffee|cofe|cofix|даблби|дринкит|шоколадница|кофемания"
    okved: ["56.10", "56.30"]
    params_file: research/niche_params/coffee.yaml
  - code: pickup_point
    name: Пункт выдачи заказов
    osm_tags:
      - {shop: outpost}
    okved: ["52.29", "82.92"]
    params_file: research/niche_params/pickup_point.yaml
```

Правило `osm_name_rules` добавляет объекты с указанными тегами, в названии или бренде которых встречается регулярное выражение `pattern`. Оно нужно, так как большинство кофеен в OSM отмечено как `amenity=cafe` без кухни. Поле `mos_ru_name_pattern` задаёт выражение для отбора заведений ниши из набора общепита data.mos.ru по названию, ниши без поля из набора не берутся. Теги OpenStreetMap и коды ОКВЭД проверяет Иван в задаче S1-I2, исправления вносит Фёдор.

## Параметры ниши

Файл `research/niche_params/<niche>.yaml` готовит Иван, читает модель Романа. Каждое число задаётся диапазоном и источником:

```yaml
niche: coffee
currency: RUB
period: month
updated: 2026-10-17
demand:
  avg_check_rub: {p10: 250, p50: 330, p90: 420, source: "https://...", note: "средний чек кофейни у дома"}
  visits_per_resident_month: {p10: 1.0, p50: 2.0, p90: 3.5, source: "https://..."}
  visits_per_worker_month: {p10: 3.0, p50: 6.0, p90: 10.0, source: "https://..."}
  max_walk_distance_m: {p10: 300, p50: 500, p90: 800, source: "https://..."}
  distance_decay_beta: {p10: 1.5, p50: 2.0, p90: 2.5, source: "https://..."}
costs:
  area_m2: {p10: 25, p50: 40, p90: 70, source: "https://..."}
  staff_count: {p10: 3, p50: 4, p90: 6, source: "https://..."}
  wage_profession: barista
  cogs_share_of_revenue: {p10: 0.25, p50: 0.30, p90: 0.35, source: "https://..."}
  other_opex_rub: {p10: 30000, p50: 60000, p90: 100000, source: "https://...", note: "коммунальные платежи, связь, эквайринг, маркетинг"}
capex_rub: {p10: 1500000, p50: 3000000, p90: 5000000, source: "https://..."}
tax_regime_default: usn_income_6
```

Для пункта выдачи блок `demand` содержит `orders_per_resident_month`, `marketplace_share` и `payout_per_order_rub`, а блок `costs` содержит `wage_profession: pickup_operator`. Если Иван не нашёл источник для числа, поле получает `source: null` и `note` с объяснением, а Роман выводит такие допущения в отчёт отдельно.

Ставки аренды лежат в `research/rent/<city>.csv`:

```
city,zone,zone_type,rent_rub_m2_month_p10,rent_rub_m2_month_p50,rent_rub_m2_month_p90,property_type,source,date
moscow,Тверской,center,4500,7000,12000,street_retail,https://...,2026-09
tula,Центральный,center,900,1400,2200,street_retail,https://...,2026-09
```

Поле `zone` совпадает с названием района из OpenStreetMap (Москва – районы, Тула – территориальные округа), чтобы Фёдор мог сопоставить ячейки с зонами. Налоги описываются в `research/taxes/2026.yaml` (ставки УСН, страховые взносы ИП, порог НДС, торговый сбор Москвы с указанием, к каким нишам он применяется).

## Данные конвейера

Фёдор формирует файлы в `data/processed/<city>/`, Роман их читает.

`hex_features.parquet`, одна строка на ячейку H3 разрешения 9:

| Поле | Тип | Единица | Описание |
| --- | --- | --- | --- |
| `h3` | str | – | индекс ячейки |
| `lat`, `lon` | float | градусы | центр ячейки |
| `district` | str | – | район для сопоставления с арендой |
| `residents` | float | человек | оценка числа жителей |
| `workers` | float | человек | оценка числа работающих днём |
| `offices_n` | int | шт. | офисные здания и бизнес-центры |
| `education_n` | int | шт. | вузы, колледжи, школы |
| `malls_n` | int | шт. | торговые центры |
| `transit_stops_n` | int | шт. | остановки наземного транспорта |
| `metro_dist_m` | float | м | расстояние до ближайшего входа в метро, пусто для Тулы |

`competitors.parquet`, одна строка на точку конкурента:

| Поле | Тип | Описание |
| --- | --- | --- |
| `poi_id` | str | идентификатор в источнике |
| `niche` | str | код ниши |
| `name`, `brand` | str | название и бренд, если известен |
| `lat`, `lon`, `h3` | float, float, str | расположение |
| `source` | str | `osm` или `mos_ru` |
| `seats` | int, может быть пусто | число посадочных мест (data.mos.ru) |

`wages.parquet`: `profession`, `salary_p25`, `salary_p50`, `salary_p75` (рублей в месяц до вычета НДФЛ), `vacancies_n`, `collected_at`, `basis`. Поле `basis` равно `direct`, если зарплата посчитана по вакансиям самой профессии, и `proxy`, если вакансий меньше четырёх и использована соседняя профессия (для бариста – официант, для оператора пункта выдачи – кассир). Модель выводит такие зарплаты в допущения отчёта.

`boundary.geojson`: граница охвата города (контур МКАД или городской округ), нужна интерфейсу и проверкам.

`addresses.parquet`: `address`, `lat`, `lon`, `h3` для поиска адреса в интерфейсе.

Способ оценки жителей и работающих Фёдор описывает в `docs/data-sources.md`. Базовый вариант – число квартир в многоквартирных домах из Реформы ЖКХ или ГИС ЖКХ, умноженное на средний размер домохозяйства по Росстату, а при отсутствии данных – площадь жилых зданий из OpenStreetMap, делённая на норму площади на человека.

## Интерфейс модели

Пакет `geostart.model` (Роман):

```python
def score_city(city: str, niche: str) -> pandas.DataFrame: ...

def evaluate_location(
    city: str,
    niche: str,
    lat: float,
    lon: float,
    area_m2: float | None = None,
    rent_rub_m2_month: float | None = None,
) -> LocationReport: ...
```

`score_city` сохраняет результат в `data/scores/<city>_<niche>.parquet` с полями `h3`, `revenue_p10`, `revenue_p50`, `revenue_p90`, `profit_p50`, `payback_months_p50` (пусто, если прибыль не положительная), `risk_level` (`low`, `medium`, `high`), `competitors_500m`. Расчёт города запускается командой `uv run python -m geostart.model score --city moscow --niche coffee`.

`LocationReport` и остальные модели ответов API лежат в `src/geostart/schemas.py`. Модель Романа возвращает `geostart.schemas.LocationReport`, API отдаёт её без преобразований.

## HTTP API

Префикс `/api/v1`, ответы в JSON, тексты ошибок на русском в поле `detail`.

| Метод и путь | Назначение |
| --- | --- |
| `GET /health` | состояние сервиса и версия данных |
| `GET /cities` | список городов из конфигурации |
| `GET /niches` | список ниш |
| `GET /hexes?city=moscow&niche=coffee` | значения по всем ячейкам города для карты |
| `GET /competitors?city=moscow&niche=coffee` | точки конкурентов |
| `GET /search?city=moscow&q=Тверская 7` | до 10 адресов по запросу |
| `POST /report` | отчёт по точке |

`GET /cities`:

```json
[
  {"code": "moscow", "name": "Москва", "center": [55.7558, 37.6176], "zoom": 11},
  {"code": "tula", "name": "Тула", "center": [54.1931, 37.6173], "zoom": 12}
]
```

`GET /hexes?city=moscow&niche=coffee`:

```json
{
  "city": "moscow",
  "niche": "coffee",
  "data_version": "2026-10-18",
  "items": [
    {"h3": "8911aa7a2c3ffff", "revenue_p50": 820000, "payback_months_p50": 31.5, "risk_level": "medium", "competitors_500m": 9}
  ]
}
```

`GET /competitors?city=moscow&niche=coffee`:

```json
[
  {"name": "Кофейня на углу", "brand": null, "lat": 55.7605, "lon": 37.6191, "source": "osm"}
]
```

`GET /search?city=moscow&q=Тверская 7`:

```json
[
  {"address": "Тверская улица, 7", "lat": 55.7601, "lon": 37.6129}
]
```

`POST /report`, запрос:

```json
{"city": "moscow", "niche": "coffee", "lat": 55.7601, "lon": 37.6129, "area_m2": 40, "rent_rub_m2_month": null}
```

`POST /report`, ответ:

```json
{
  "city": "moscow",
  "niche": "coffee",
  "location": {"lat": 55.7601, "lon": 37.6129, "h3": "8911aa7a2c3ffff", "address": "Тверская улица, 7"},
  "revenue_month": {"p10": 610000, "p50": 820000, "p90": 1050000},
  "costs_month": {"rent": 280000, "payroll": 260000, "cogs": 246000, "taxes": 49200, "other": 60000, "total": 895200},
  "profit_month_p50": -75200,
  "capex_rub_p50": 3000000,
  "payback_months_p50": null,
  "risk_level": "high",
  "factors": [
    {"code": "competitors_500m", "name": "Кофейни в радиусе 500 м", "value": 14, "unit": "шт.", "effect_rub": -180000},
    {"code": "workers", "name": "Работающие в ячейке и рядом", "value": 5200, "unit": "чел.", "effect_rub": 210000}
  ],
  "competitors": [
    {"name": "Кофейня на углу", "lat": 55.7605, "lon": 37.6191, "distance_m": 120}
  ],
  "assumptions": [
    {"name": "Средний чек", "value": 330, "unit": "₽", "source": "https://..."}
  ],
  "data_version": "2026-10-18"
}
```

Поле `effect_rub` показывает, на сколько рублей в месяц изменится выручка p50, если значение фактора заменить медианой по городу. Факторы отсортированы по модулю эффекта.

Ошибки:

| Код | Пример `detail` |
| --- | --- |
| 404 | «Город tula ещё не рассчитан, выберите moscow или дождитесь загрузки данных» |
| 422 | «Точка вне границ города moscow, выберите место внутри МКАД» |

Алексей строит интерфейс по этим примерам. Заглушки ответов лежат в `web/src/mocks/` и переключаются переменной окружения `VITE_USE_MOCKS=true`.
