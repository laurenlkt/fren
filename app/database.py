"""
All the SQLite code for Fren lives here.

Step 2 only needs one table: safety_events.
More tables (sessions, moods, plans) are added in later steps.
"""

import sqlite3
from datetime import datetime, timezone

import config


def get_connection():
    """Open a connection to the database file (creating it if needed)."""
    config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(config.DATABASE_PATH)
    connection.row_factory = sqlite3.Row  # lets us use row["column_name"]
    return connection


def init_db():
    """Create the tables if they don't exist yet. Safe to run many times."""
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS safety_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT,
                created_at  TEXT NOT NULL,  -- UTC time, ISO format
                source      TEXT NOT NULL,  -- keyword / classifier / classifier_error / output_filter
                category    TEXT,           -- e.g. "self-harm" (never the message itself)
                text        TEXT            -- ONLY filled if config.STORE_FLAGGED_TEXT is True
            )
            """
        )


def now_utc():
    """The current time as text, e.g. '2026-10-13T21:30:00+00:00'."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_safety_event(user_id, source, category=None, text=None):
    """
    Record that a safety check fired.

    The `text` argument is thrown away unless config.STORE_FLAGGED_TEXT
    is True, so callers can always pass it without worrying.
    """
    stored_text = text if config.STORE_FLAGGED_TEXT else None
    init_db()
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO safety_events (user_id, created_at, source, category, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, now_utc(), source, category, stored_text),
        )
