from datetime import date

import h3
import pandas as pd

from geostart.config import NameRule, NicheConfig, get_city
from geostart.pipeline import run, trudvsem


def test_coffee_name_rule_adds_cafes_without_cuisine() -> None:
    city = get_city("tula")
    cell = h3.latlng_to_cell(54.19, 37.62, city.h3_resolution)
    pois = pd.DataFrame(
        {
            "city": ["tula"] * 3,
            "osm_id": ["n1", "n2", "n3"],
            "lat": [54.19] * 3,
            "lon": [37.62] * 3,
            "amenity": ["cafe", "cafe", "cafe"],
            "cuisine": [None, None, "coffee_shop"],
            "shop": [None] * 3,
            "name": ["Кофе Культ", "Столовая", "Без вывески"],
            "brand": [None] * 3,
        }
    )
    niche = NicheConfig(
        code="coffee",
        name="Кофейня",
        osm_tags=[{"amenity": "cafe", "cuisine": "coffee_shop"}],
        osm_name_rules=[NameRule(tags={"amenity": "cafe"}, pattern="(?i)коф|coffee")],
        okved=[],
        params_file="",
    )
    competitors = run.build_osm_competitors(city, [niche], pois, {cell})
    assert sorted(competitors["poi_id"]) == ["n1", "n3"]


def test_proxy_wages_are_used_when_direct_vacancies_are_scarce(tmp_path, monkeypatch) -> None:
    def fake_fetch(region: str, query: str) -> list[dict]:
        if query == "официант":
            return [
                {"id": f"w{index}", "salary_min": 40000 + index * 1000, "creation-date": "2026-09-01"}
                for index in range(6)
            ]
        if query == "кассир":
            return [
                {"id": f"c{index}", "salary_min": 50000 + index * 1000, "creation-date": "2026-09-01"}
                for index in range(6)
            ]
        return [{"id": "b1", "salary_min": 60000, "creation-date": "2026-09-01"}]

    monkeypatch.setattr(trudvsem, "fetch_vacancies", fake_fetch)
    wages = trudvsem.build_wages("7100000000000", tmp_path, date(2026, 10, 14))
    assert wages["profession"].tolist() == ["barista", "pickup_operator"]
    assert wages["basis"].tolist() == ["proxy", "proxy"]
    assert wages.loc[wages["profession"] == "barista", "vacancies_n"].item() == 6


def test_vacancy_cache_keeps_no_contacts(tmp_path, monkeypatch) -> None:
    import json

    vacancy = {
        "id": "v1",
        "job-name": "Бариста",
        "salary_min": 70000,
        "salary_max": 90000,
        "creation-date": "2026-09-01",
        "contact_person": "Иванова Анна",
        "contact_list": [{"contact_type": "Телефон", "contact_value": "+7 900 000-00-00"}],
        "company": {"email": "hr@example.ru"},
    }
    monkeypatch.setattr(trudvsem, "fetch_vacancies", lambda region, query: [vacancy])
    loaded = trudvsem.load_vacancies("7700000000000", "barista", ["бариста"], tmp_path)
    cached_text = (tmp_path / "7700000000000_barista.json").read_text(encoding="utf-8")
    assert set(loaded[0]) == set(trudvsem.CACHED_VACANCY_FIELDS)
    assert "Иванова" not in cached_text
    assert "hr@example.ru" not in cached_text

    legacy_path = tmp_path / "7700000000000_legacy.json"
    legacy_path.write_text(json.dumps([vacancy], ensure_ascii=False), encoding="utf-8")
    trudvsem.load_vacancies("7700000000000", "legacy", [], tmp_path)
    assert "+7 900" not in legacy_path.read_text(encoding="utf-8")
