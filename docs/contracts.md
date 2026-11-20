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
      - {amenity: fast_food, cuisine: coffee_shop}
    osm_name_rules:
      - tags: {amenity: cafe}
        pattern: "(?i)коф|coffee|cofe|cofix|даблби|дринкит|шоколадница|кофемания|skuratov"
      - tags: {amenity: fast_food}
        pattern: "(?i)коф|coffee|cofe|cofix|даблби|дринкит|skuratov"
    mos_ru_name_pattern: "(?i)коф|coffee|cofe|cofix|даблби|дринкит|шоколадница|кофемания|skuratov"
    okved: ["56.10", "56.30"]
    demand_kind: visits
    params_file: research/niche_params/coffee.yaml
  - code: pickup_point
    name: Пункт выдачи заказов
    osm_tags:
      - {shop: outpost}
    okved: ["47.91", "52.29", "53.20", "82.92"]
    demand_kind: orders
    params_file: research/niche_params/pickup_point.yaml
  - code: fast_food
    name: Фастфуд
    osm_tags:
      - {amenity: fast_food}
    exclude_niches: [coffee]
    okved: ["56.10"]
    demand_kind: visits
    params_file: research/niche_params/fast_food.yaml
```

Пример сокращён, полный список правил и всех семи ниш лежит в `config/niches.yaml`. Кроме кофейни и пункта выдачи в нём описаны продукты у дома (`grocery`), салон красоты и парикмахерская (`beauty_salon`), фастфуд (`fast_food`), пекарня и кондитерская (`bakery`) и цветы (`flowers`).

Поле `demand_kind` выбирает формулу спроса. Тип `visits` описывает покупки жителей, работающих и прохожих, тип `orders` описывает заказы маркетплейсов с переходом к ближайшему пункту. Новая ниша с одним из этих типов подключается записью в `config/niches.yaml`, файлом параметров в `research/niche_params/`, блоком нормативов в `research/economics/norms.yaml` и кодом ниши в списках `applies_to` налогового файла без изменения кода модели. Поле `exclude_niches` убирает из ниши объекты, которые уже отнесены к перечисленным нишам, например кофейни с тегом `amenity=fast_food`.

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

Для ниш типа `orders` блок `demand` содержит `orders_per_resident_month`, `marketplace_share` и `payout_per_order_rub`, а блок `costs` содержит `wage_profession: pickup_operator`. Ниши типа `visits` могут задать предел покупок в день `max_units_per_day`, у кофейни он называется `max_cups_per_day`, а также покупки прохожих у метро и остановок. Поле `wage_profession` выбирает профессию из запросов «Работы России» в `src/geostart/pipeline/trudvsem.py:PROFESSION_QUERIES`. Вес внешней альтернативы модели Хаффа задаётся в `demand.outside_option_weight`. Блок `benchmarks` содержит ориентиры месячной выручки действующей точки `revenue_rub_month_<city>` для сверки масштаба модели, в расчёт он не входит.

Значение, которое заметно отличается по городам, записывается рядом с базовым полем с суффиксом города, например `avg_check_rub_moscow` и `avg_check_rub_tula` в блоке `demand` или `capex_rub_moscow` на верхнем уровне. Функция `src/geostart/research.py:city_parameters` при чтении файла подставляет значение города вместо базового, а поля других городов отбрасывает. Если у города нет своего поля, используется базовое. Если Иван не нашёл источник для числа, поле получает `source: null` и `note` с объяснением, а Роман выводит такие допущения в отчёт отдельно.

Ставки аренды лежат в `research/rent/<city>.csv`:

```
city,zone,zone_type,rent_rub_m2_month_p10,rent_rub_m2_month_p50,rent_rub_m2_month_p90,property_type,source,date
moscow,Тверской,center,4500,7000,12000,street_retail,https://...,2026-09
tula,Центральный,center,900,1400,2200,street_retail,https://...,2026-09
```

Необязательная колонка `note` объясняет, по каким данным построена строка. Поле `zone` совпадает с названием района из OpenStreetMap (Москва – районы, Тула – территориальные округа), чтобы Фёдор мог сопоставить ячейки с зонами. Налоги описываются в `research/taxes/2026.yaml` (ставки УСН, страховые взносы ИП, порог НДС, торговый сбор Москвы с указанием, к каким нишам он применяется).

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
| 422 | «Значение поля «площадь» должно быть больше 0» |

Алексей строит интерфейс по этим примерам. Заглушки ответов лежат в `web/src/mocks/` и переключаются переменной окружения `VITE_USE_MOCKS=true`.

## HTTP API v2

Префикс `/api/v2`, ответы в JSON. Версия 2 добавляет финансовый движок и работает рядом с `/api/v1`, пути и ответы первой версии не меняются. Полная схема запросов и ответов лежит в [api-v2.openapi.json](api-v2.openapi.json) в формате OpenAPI 3.1, формулы описаны в [economics.md](economics.md).

| Метод и путь | Назначение |
| --- | --- |
| `POST /economics` | помесячная финансовая модель точки |
| `POST /credit-check` | сверка бизнес-плана заявки на кредит с моделью |
| `GET /norms/{niche}?city=tula` | нормативы и параметры затрат ниши в городе с источниками |
| `GET /credit-products` | кредитные продукты с условиями и источниками |

Запрос `POST /economics` с выручкой по модели ГеоСтарта:

```json
{
  "city": "tula",
  "niche": "coffee",
  "demand": {
    "source": "geostart",
    "lat": 54.193,
    "lon": 37.617
  },
  "financing": {
    "loan_share": 0.7,
    "product": "vtb_express",
    "business_age_months": 24,
    "grace_months": 3
  },
  "tax": {
    "legal_form": "ip",
    "regime": "auto"
  },
  "horizon_months": 36,
  "start_month": 1,
  "start_year": 2027
}
```

Обязательны поля `city`, `niche` и `demand`. Необязательные блоки `premises` с полями `area_m2`, `rent_rub_m2_month`, `security_deposit_months` и `central_district`, `operations` с полями `staff_count`, `salary_rub_month`, `cogs_share` и `other_opex_rub_month`, `investment` с полями `capex_rub`, `working_capital_rub` и `franchise_fee_rub` заменяют значения исследования во всех сценариях. Блок `financing` принимает сумму `loan_amount_rub` или долю `loan_share`, ставку `rate_annual`, срок `term_months`, график `schedule`, льготный период `grace_months`, код продукта `product` и возраст бизнеса `business_age_months`. Без `financing` кредит не берётся, а ставка и срок для расчёта предельного кредита берутся из нормативов. Поля `start_month` и `start_year` задают месяц открытия, от них зависят налоговые годы и доступность АУСН. Поле `tax.regime` принимает `auto`, `usn_income_6`, `usn_income_minus_expenses_15`, `patent`, `ausn_income_8` и `ausn_income_minus_expenses_20`. Неизвестные поля отклоняются с кодом 422.

| Поле `demand` | Содержимое |
| --- | --- |
| `{"source": "geostart", "lat", "lon"}` | выручка по модели Хаффа в точке |
| `{"source": "revenue", "revenue_month": {"p10", "p50", "p90"}, "provider"}` | внешняя оценка выручки в месяц |
| `{"source": "traffic", "visitors_per_day", "conversion", "avg_check_rub", "provider"}` | трафик, конверсия и средний чек, каждый как `{"p10", "p50", "p90"}`, средний чек можно не указывать |

Сокращённый ответ на данных Тулы:

```json
{
  "city": "tula",
  "niche": "coffee",
  "versions": {
    "model": "economics-0.2.0",
    "norms": "2026-11-18",
    "data": "2026-10-16",
    "taxes": "2026-10-18"
  },
  "scenarios": 200,
  "horizon_months": 36,
  "start_month": 1,
  "start_year": 2027,
  "discount_rate_annual": 0.2,
  "demand": {
    "source": "geostart",
    "provider": null,
    "revenue_steady_month": {
      "p10": 457441,
      "p50": 761868,
      "p90": 1223136
    },
    "h3": "891183931c7ffff",
    "district": "Центральный"
  },
  "tax": {
    "regime": "patent",
    "name": "Патентная система",
    "legal_form": "ip",
    "chosen_automatically": true,
    "explanation": "Режим Патентная система выбран по наименьшей сумме налогов и взносов за горизонт расчёта, он дешевле режима АУСН «Доходы минус расходы» 20% на 770 064 ₽ по медиане сценариев",
    "options": [
      {
        "regime": "usn_income_6",
        "name": "УСН «Доходы» 6%",
        "eligible": true,
        "reason": null,
        "taxes_first_year_p50": 382298,
        "taxes_horizon_p50": 1295326,
        "contributions_horizon_p50": 1869829,
        "burden_horizon_p50": 3223633
      },
      {
        "regime": "usn_income_minus_expenses_15",
        "name": "УСН «Доходы минус расходы» 15%",
        "eligible": true,
        "reason": null,
        "taxes_first_year_p50": 141911,
        "taxes_horizon_p50": 953300,
        "contributions_horizon_p50": 1869829,
        "burden_horizon_p50": 3074389
      }
    ]
  },
  "investment": {
    "capex": 2201250,
    "franchise_fee": 0.0,
    "security_deposit": 31715,
    "working_capital": 233340,
    "total": {
      "p10": 1494524,
      "p50": 2499409,
      "p90": 3887697
    },
    "loan": 1749586,
    "own_funds": 749823,
    "items": [
      {
        "code": "renovation",
        "name": "Ремонт помещения",
        "amount": 770438,
        "life_months": 60
      },
      {
        "code": "equipment",
        "name": "Кофейное и холодильное оборудование",
        "amount": 990562,
        "life_months": 60
      }
    ]
  },
  "steady_month": {
    "revenue": 667996,
    "cogs": 167876,
    "rent": 41966,
    "wages": 183281,
    "payroll_contributions": 54147,
    "other": 31875,
    "ebitda": 188850,
    "tax": 2734,
    "owner_contributions": 5444,
    "vat": 0.0,
    "profit": 180673
  },
  "metrics": {
    "npv": {
      "p10": -3483301,
      "p50": 3155252,
      "p90": 12137067
    },
    "irr_annual": {
      "p10": -0.89,
      "p50": 1.13,
      "p90": 6.33
    },
    "payback_months": {
      "p10": 6.08,
      "p50": 14.51,
      "p90": null
    },
    "first_profit_month": {
      "p10": 1.0,
      "p50": 2.5,
      "p90": null
    },
    "probability_no_payback": 0.24,
    "probability_loss": 0.14,
    "risk_level": "low",
    "break_even_revenue_month": {
      "p10": 280047,
      "p50": 450320,
      "p90": 639397
    },
    "break_even_units_per_day": {
      "p10": 32.9,
      "p50": 52.9,
      "p90": 75.12
    },
    "unit_name": "чек",
    "unit_value_rub": 280
  },
  "credit": {
    "product": "vtb_express",
    "product_name": "ВТБ, экспресс-кредит для малого бизнеса",
    "amount": 1749586,
    "rate_annual": 0.26,
    "term_months": 36,
    "grace_months": 3,
    "schedule": "annuity",
    "first_payment": 37908,
    "dscr_min": {
      "p10": -1.07,
      "p50": 2.46,
      "p90": 7.61
    },
    "dscr_monthly_min": {
      "p10": -5.42,
      "p50": -0.9,
      "p90": 3.52
    },
    "months_below_threshold_p50": 2.0,
    "dscr_threshold": 1.25,
    "probability_dscr_below_threshold": 0.3,
    "max_loan_rub": {
      "p10": 0.0,
      "p50": 4083950,
      "p90": 10168722
    }
  },
  "monthly": [
    {
      "month": 1,
      "calendar_month": 1,
      "revenue": 333998,
      "cogs": 83938,
      "rent": 41966,
      "payroll": 237429,
      "other": 31875,
      "taxes": 4560,
      "ebitda": -61210,
      "depreciation": 33979,
      "interest": 25269,
      "principal": 0.0,
      "net_profit": -91038,
      "owner_cash_flow": -91038,
      "cumulative_project_cash": -1731861,
      "dscr": -2.6
    }
  ],
  "cash_band": [
    {
      "month": 1,
      "p10": -3907572,
      "p50": -2489847,
      "p90": -1525514
    }
  ],
  "years": [
    {
      "year": 1,
      "revenue": 7187632,
      "operating_costs": 5541576,
      "ebitda": 1646056,
      "depreciation": 407750,
      "ebit": 1238306,
      "taxes": 98127,
      "interest": 283067,
      "principal": 241252,
      "net_profit": 1264863,
      "operating_cash_flow": 1547929
    }
  ],
  "assumptions": [
    {
      "name": "Источник выручки",
      "value": "Модель Хаффа ГеоСтарт по открытым данным, 200 сценариев параметров спроса",
      "unit": "",
      "source": "https://www.openstreetmap.org"
    }
  ],
  "warnings": [
    "В 3% сценариев выручка или штат выше лимитов патента, для них налог посчитан по УСН «Доходы»",
    "Сезонность ниши не исследована, выручка распределена по месяцам равномерно"
  ]
}
```

Список `tax.options` и `investment.items` в примере сокращены до двух элементов, списки `monthly`, `cash_band`, `years` и `assumptions` до первого. Поле `metrics` содержит также `discounted_payback_months`, `profit_steady_month`, `ebitda_margin_p50`, `safety_margin` и `contribution_margin_per_unit`, поле `credit` содержит `total_interest` и `dscr_first_year`. Строка месяца содержит амортизацию `depreciation` и DSCR месяца `dscr`, пустой без платежей по кредиту. Строка года содержит `depreciation` и `ebit`. Диапазоны с возможными пустыми значениями имеют тип `OptionalRange`, в нём `null` означает, что показатель не достигается в этой доле сценариев.

Запрос `POST /credit-check` содержит блок `economics` в формате запроса `/economics` и бизнес-план заявки:

```json
{
  "economics": {
    "city": "tula",
    "niche": "coffee",
    "demand": {
      "source": "geostart",
      "lat": 54.193,
      "lon": 37.617
    },
    "start_month": 1,
    "start_year": 2027
  },
  "plan": {
    "revenue_month_rub": 1500000,
    "capex_rub": 1000000,
    "payback_months": 8,
    "loan_amount_rub": 2000000,
    "product": "vtb_express",
    "business_age_months": 24
  }
}
```

Ответ:

```json
{
  "verdict": "not_confirmed",
  "summary": [
    "Выручка в месяц плана 1 500 000 ₽ выше p90 модели, план оптимистичнее модели",
    "Вложения плана 1 000 000 ₽ ниже p10 модели, план оптимистичнее модели",
    "Окупаемость плана 8 мес. в диапазоне p10-p90 модели",
    "Доля сценариев с покрытием долга не ниже 1,25 составляет 64%"
  ],
  "checks": [
    {
      "code": "revenue_month",
      "name": "Выручка в месяц",
      "plan_value": 1500000,
      "model": {
        "p10": 457441,
        "p50": 761868,
        "p90": 1223136
      },
      "percentile": 98.5,
      "status": "above",
      "risk_flag": true,
      "comment": "Выручка в месяц плана 1 500 000 ₽ выше p90 модели, план оптимистичнее модели"
    }
  ],
  "loan_amount_rub": 2000000,
  "probability_dscr_ok": 0.64,
  "max_loan_rub": {
    "p10": 0.0,
    "p50": 4331225,
    "p90": 10784416
  },
  "economics": {}
}
```

Флаг риска ставится, если выручка плана выше p90 модели, вложения ниже p10 или окупаемость короче p10. Вердикт `confirmed` выдаётся без флагов при доле сценариев с DSCR не ниже порога от 80%, вердикт `not_confirmed` при двух флагах и больше или при доле ниже 50%, в остальных случаях выдаётся `needs_review`. Поле `economics` содержит полный ответ `/economics` с кредитом из плана.

Ошибки второй версии отдаются в формате `application/problem+json`:

```json
{
  "type": "about:blank",
  "title": "Некорректные параметры расчёта",
  "status": 422,
  "detail": "Оценка должна соблюдать порядок p10 ≤ p50 ≤ p90; Поле «foo» не поддерживается",
  "errors": [
    {"field": "demand.revenue_month", "message": "Оценка должна соблюдать порядок p10 ≤ p50 ≤ p90"},
    {"field": "foo", "message": "Поле «foo» не поддерживается"}
  ]
}
```

Поле `errors` есть только у ошибок проверки запроса. Код 404 означает неизвестный город, нишу или отсутствие данных города, код 422 означает некорректные параметры, точку вне границы города или недоступный налоговый режим.

После изменения схем API v2 контракт пересобирается командой `uv run python -m geostart.api.openapi`. Тест `tests/test_api_v2.py` сравнивает файл контракта со схемой приложения и падает, если контракт не обновлён.
