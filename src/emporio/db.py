"""Small SQLite file for what must survive a request: conversation checkpoints, handoffs and the daily spend."""
import sqlite3
from datetime import date

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS handoffs (protocol TEXT PRIMARY KEY, thread_id TEXT, reason TEXT, summary TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS spend (day TEXT PRIMARY KEY, usd REAL NOT NULL);
"""


def connect() -> sqlite3.Connection:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(config.STATE_DIR / "app.db", check_same_thread=False)
    connection.executescript(_SCHEMA)
    return connection


def add_spend(usd: float) -> None:
    with connect() as c:
        c.execute("INSERT INTO spend VALUES (?, ?) ON CONFLICT(day) DO UPDATE SET usd = usd + excluded.usd",
                  (date.today().isoformat(), usd))


def spent_today() -> float:
    with connect() as c:
        row = c.execute("SELECT usd FROM spend WHERE day = ?", (date.today().isoformat(),)).fetchone()
    return row[0] if row else 0.0


def save_handoff(protocol: str, thread_id: str, reason: str, summary: str, created_at: str) -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO handoffs VALUES (?, ?, ?, ?, ?)", (protocol, thread_id, reason, summary, created_at))
