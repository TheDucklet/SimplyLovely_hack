import csv
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[1]


def test_gir_bo_coffee_selection_meets_numeric_filters() -> None:
    path = REPOSITORY_ROOT / "research" / "coffee" / "gir_bo_coffee.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    assert 30 <= len(rows) <= 50
    seen = set()
    for row in rows:
        key = (row["inn"], row["year"])
        assert re.fullmatch(r"\d{10}", row["inn"])
        assert 3_000_000 <= int(row["revenue_rub"]) <= 60_000_000
        assert not row["cogs_rub"] or int(row["cogs_rub"]) < int(row["revenue_rub"])
        assert row["report_url"] and row["address_url"]
        assert key not in seen
        seen.add(key)


def test_candidate_selection_has_required_shape_and_size() -> None:
    path = REPOSITORY_ROOT / "research" / "coffee" / "candidates.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    assert 60 <= len(rows) <= 80
    assert set(rows[0]) == {"name", "city", "address", "address_url"}
    assert {row["city"] for row in rows} <= {"Москва", "Тула"}
    assert all(row["address_url"].startswith("http") for row in rows)
