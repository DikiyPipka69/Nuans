"""Тесты слоя базы данных. FastAPI здесь не нужен."""
import sqlite3

import pytest

from app import db


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    db.init()


def test_init_is_idempotent():
    db.init()
    db.init()
    assert db.list_leads() == []


def test_add_and_list_newest_first():
    db.add_lead("Анна", "79001234567", "Педикюр")
    db.add_lead("Мария", "79007654321", "Маникюр")
    leads = db.list_leads()
    assert [l["name"] for l in leads] == ["Мария", "Анна"]


def test_sql_injection_is_stored_as_plain_text():
    db.add_lead("Анна'; DROP TABLE leads;--", "79001234567", "Педикюр")
    assert db.list_leads()[0]["name"] == "Анна'; DROP TABLE leads;--"


def test_recent_duplicate_detection():
    assert not db.has_recent_lead("79001234567")
    db.add_lead("Анна", "79001234567", "Педикюр")
    assert db.has_recent_lead("79001234567")
    assert not db.has_recent_lead("79007654321")


def test_old_lead_is_not_recent():
    db.add_lead("Анна", "79001234567", "Педикюр")
    conn = sqlite3.connect(db._path())
    conn.execute("UPDATE leads SET created_at = datetime('now', '-1 hour')")
    conn.commit()
    conn.close()
    assert not db.has_recent_lead("79001234567")


def test_old_leads_are_trimmed(monkeypatch):
    monkeypatch.setattr(db, "MAX_LEADS", 5)
    for i in range(9):
        db.add_lead(f"Имя{i}", f"7900000000{i}", "Услуга")
    leads = db.list_leads()
    assert len(leads) == 5 and leads[0]["name"] == "Имя8" and leads[-1]["name"] == "Имя4"
