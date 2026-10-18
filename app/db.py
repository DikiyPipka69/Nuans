"""Работа с SQLite. Только стандартная библиотека, без ORM."""
import os
import sqlite3
from contextlib import closing
from pathlib import Path


def _path() -> str:
    return os.environ.get("DB_PATH", "data/leads.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_path())
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    Path(_path()).parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                service TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()


def add_lead(name: str, phone: str, service: str) -> int:
    # Параметры подставляются через ?, поэтому SQL-инъекции невозможны.
    with closing(_connect()) as conn:
        cur = conn.execute(
            "INSERT INTO leads (name, phone, service) VALUES (?, ?, ?)",
            (name, phone, service),
        )
        conn.commit()
        return cur.lastrowid


def list_leads(limit: int = 200) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, name, phone, service, created_at FROM leads "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
