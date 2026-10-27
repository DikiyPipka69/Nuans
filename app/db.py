"""Работа с SQLite. Только стандартная библиотека, без ORM."""
import os
import sqlite3
from contextlib import closing
from pathlib import Path

MAX_LEADS = 2000  # хранится не больше стольких последних заявок: диск не переполнить


def _path() -> str:
    return os.environ.get("DB_PATH", "data/leads.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_path(), timeout=5)  # при занятой базе ждём, а не падаем
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
        new_id = cur.lastrowid
        conn.execute("DELETE FROM leads WHERE id <= ?", (new_id - MAX_LEADS,))
        conn.commit()
        return new_id


def list_leads(limit: int = 200) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, name, phone, service, created_at FROM leads "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def has_recent_lead(phone: str, minutes: int = 10) -> bool:
    """Была ли заявка с этого телефона за последние минуты (двойной клик или спам)."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT 1 FROM leads WHERE phone = ? AND created_at >= datetime('now', ?) LIMIT 1",
            (phone, f"-{minutes} minutes"),
        ).fetchone()
    return row is not None
