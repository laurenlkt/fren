"""
All the SQLite code for Fren lives here. No other file writes SQL.

Tables:
  users            - one row per anonymous participant
  sessions         - one row per session (mood, times, plan, human step)
  session_messages - the chat of the CURRENT session only. It is deleted
                     as soon as the session closes, so chats are never kept.
  safety_events    - when a safety check fired (no message text by default)
"""

import secrets
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
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id             TEXT PRIMARY KEY,   -- random anonymous ID
                created_at     TEXT NOT NULL,
                min_gap_hours  REAL NOT NULL       -- chosen by the participant
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             TEXT NOT NULL,
                started_at          TEXT NOT NULL,
                ended_at            TEXT,              -- empty while the session is open
                end_reason          TEXT,              -- completed / time_limit / message_limit / crisis
                stage               TEXT NOT NULL,     -- current stage, or "ended"
                user_message_count  INTEGER NOT NULL DEFAULT 0,
                stage_message_count INTEGER NOT NULL DEFAULT 0,
                mood                INTEGER NOT NULL,  -- check-in mood score
                plan_text           TEXT,
                human_step_taken    INTEGER NOT NULL DEFAULT 0,  -- 1 = participant says they sent it
                human_step_choice   TEXT,              -- sent / later / skipped (empty = not answered)
                draft_count         INTEGER NOT NULL DEFAULT 0   -- reach-out drafts asked for
            );

            CREATE TABLE IF NOT EXISTS session_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  INTEGER NOT NULL,
                role        TEXT NOT NULL,   -- "user" or "fren"
                text        TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS safety_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT,
                created_at  TEXT NOT NULL,  -- UTC time, ISO format
                source      TEXT NOT NULL,  -- keyword / classifier / classifier_error / output_filter
                category    TEXT,           -- e.g. "self-harm" (never the message itself)
                text        TEXT            -- ONLY filled if config.STORE_FLAGGED_TEXT is True
            );
            """
        )
        _add_missing_columns(connection)


def _add_missing_columns(connection):
    """
    Databases made by an earlier version of Fren may be missing newer
    columns. Add them, so you don't have to delete your test data.
    """
    existing = [row["name"] for row in connection.execute("PRAGMA table_info(sessions)")]
    if "human_step_choice" not in existing:
        connection.execute("ALTER TABLE sessions ADD COLUMN human_step_choice TEXT")
    if "draft_count" not in existing:
        connection.execute("ALTER TABLE sessions ADD COLUMN draft_count INTEGER NOT NULL DEFAULT 0")


# ---------------------------------------------------------------------------
# Time helpers. All times are stored as UTC text, e.g. "2026-10-13T21:30:00+00:00"
# ---------------------------------------------------------------------------
def now_utc():
    return datetime.now(timezone.utc)


def to_text(moment):
    return moment.isoformat(timespec="seconds")


def from_text(text):
    return datetime.fromisoformat(text) if text else None


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def create_user(min_gap_hours):
    """Make a new anonymous participant and return their random ID."""
    user_id = secrets.token_urlsafe(16)  # random and unguessable
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO users (id, created_at, min_gap_hours) VALUES (?, ?, ?)",
            (user_id, to_text(now_utc()), min_gap_hours),
        )
    return user_id


def get_user(user_id):
    """Return the user's row, or None if there's no such user."""
    if not user_id:
        return None
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def set_user_gap(user_id, min_gap_hours):
    with get_connection() as connection:
        connection.execute(
            "UPDATE users SET min_gap_hours = ? WHERE id = ?", (min_gap_hours, user_id)
        )


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def create_session(user_id, mood, started_at):
    """Start a new session at the first stage. Returns the new session's ID."""
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO sessions (user_id, started_at, stage, mood) VALUES (?, ?, ?, ?)",
            (user_id, to_text(started_at), config.STAGES[0], mood),
        )
        return cursor.lastrowid


def get_session(session_id):
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()


def get_open_session(user_id):
    """The user's session that hasn't ended yet, or None."""
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM sessions WHERE user_id = ? AND ended_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()


def get_last_ended_session(user_id):
    """The user's most recent finished session, or None."""
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM sessions WHERE user_id = ? AND ended_at IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()


# Only these columns may be changed by update_session (a safety net so a
# typo can never build broken SQL).
_UPDATABLE_SESSION_COLUMNS = {
    "ended_at", "end_reason", "stage", "user_message_count",
    "stage_message_count", "plan_text", "human_step_taken",
    "human_step_choice", "draft_count",
}


def update_session(session_id, **changes):
    """
    Change some columns of a session, e.g.
        update_session(5, stage="focus", stage_message_count=0)
    """
    for column in changes:
        if column not in _UPDATABLE_SESSION_COLUMNS:
            raise ValueError(f"Can't update column {column!r}")
    assignments = ", ".join(f"{column} = ?" for column in changes)
    values = list(changes.values()) + [session_id]
    with get_connection() as connection:
        connection.execute(f"UPDATE sessions SET {assignments} WHERE id = ?", values)


# ---------------------------------------------------------------------------
# Messages of the current session (deleted when the session closes)
# ---------------------------------------------------------------------------
def add_message(session_id, role, text):
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO session_messages (session_id, role, text, created_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, role, text, to_text(now_utc())),
        )


def get_messages(session_id):
    with get_connection() as connection:
        return connection.execute(
            "SELECT role, text FROM session_messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()


def delete_messages(session_id):
    with get_connection() as connection:
        connection.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))


# ---------------------------------------------------------------------------
# Safety events
# ---------------------------------------------------------------------------
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
            (user_id, to_text(now_utc()), source, category, stored_text),
        )
