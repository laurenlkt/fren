"""
The researcher dashboard: password check and the numbers it shows.

RULES this file follows:
  - AGGREGATES ONLY. Every number is a count or an average across
    participants. No participant IDs, no plans, no message text, ever,
    even if config.STORE_FLAGGED_TEXT is True. The SQL below never even
    selects those columns.
  - The dashboard is OFF unless the RESEARCH_PASSWORD environment variable
    is set. There is no default password.
  - The password is compared in "constant time" (secrets.compare_digest),
    so an attacker can't guess it letter by letter from how long the
    check takes.
"""

import os
import secrets
from datetime import date, timedelta

from app import database

RESEARCH_USERNAME = "researcher"


def research_password():
    """The password from the environment, or None if it isn't set."""
    password = os.environ.get("RESEARCH_PASSWORD", "").strip()
    return password or None


def credentials_ok(username, password):
    """
    True only if both match. Both comparisons always run (no shortcut), and
    each uses compare_digest, so the time taken doesn't leak anything.
    """
    expected = research_password()
    if expected is None:
        return False
    username_ok = secrets.compare_digest(username.encode("utf-8"), RESEARCH_USERNAME.encode("utf-8"))
    password_ok = secrets.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))
    return username_ok and password_ok


# ---------------------------------------------------------------------------
# The numbers
# ---------------------------------------------------------------------------
# SQLite turns a time into "the Monday of that week" like this:
# go back 6 days, then forward to the next Monday.
WEEK_START = "date({column}, '-6 days', 'weekday 1')"


def summary():
    """Everything the dashboard shows, as plain numbers."""
    database.init_db()
    with database.get_connection() as connection:
        def one_number(sql):
            return connection.execute(sql).fetchone()[0] or 0

        totals = {
            "participants": one_number("SELECT COUNT(*) FROM users"),
            "sessions": one_number("SELECT COUNT(*) FROM sessions"),
            "human_steps_taken": one_number("SELECT COUNT(*) FROM sessions WHERE human_step_taken = 1"),
            "safety_events": one_number("SELECT COUNT(*) FROM safety_events"),
        }

        # Per week: sessions started, average check-in mood, human steps taken.
        session_weeks = connection.execute(
            f"""
            SELECT {WEEK_START.format(column="started_at")} AS week,
                   COUNT(*)                                 AS sessions,
                   ROUND(AVG(mood), 2)                      AS average_mood,
                   SUM(human_step_taken)                    AS human_steps_taken
            FROM sessions
            GROUP BY week
            """
        ).fetchall()

        safety_weeks = connection.execute(
            f"""
            SELECT {WEEK_START.format(column="created_at")} AS week, COUNT(*) AS events
            FROM safety_events
            GROUP BY week
            """
        ).fetchall()

        # What participants chose at the reach-out step (finished sessions).
        choices = connection.execute(
            """
            SELECT COALESCE(human_step_choice, 'not_answered') AS choice, COUNT(*) AS count
            FROM sessions
            WHERE ended_at IS NOT NULL
            GROUP BY choice
            """
        ).fetchall()

        # Safety events by which check fired, and by category.
        # (The "text" column is deliberately never read here.)
        by_source = connection.execute(
            "SELECT source, COUNT(*) AS count FROM safety_events GROUP BY source ORDER BY count DESC"
        ).fetchall()
        by_category = connection.execute(
            """
            SELECT COALESCE(category, 'none') AS category, COUNT(*) AS count
            FROM safety_events GROUP BY category ORDER BY count DESC
            """
        ).fetchall()

    return {
        "totals": totals,
        "weeks": _combine_weeks(session_weeks, safety_weeks),
        "human_step_choices": {
            "sent": 0, "later": 0, "skipped": 0, "not_answered": 0,
            **{row["choice"]: row["count"] for row in choices},
        },
        "safety_by_source": [dict(row) for row in by_source],
        "safety_by_category": [dict(row) for row in by_category],
    }


def _combine_weeks(session_weeks, safety_weeks):
    """
    One row per week, from the first week with any data to the last,
    INCLUDING empty weeks (shown as 0), so the charts' time axis is honest.
    """
    sessions = {row["week"]: row for row in session_weeks}
    safety = {row["week"]: row["events"] for row in safety_weeks}
    all_weeks = sorted(set(sessions) | set(safety))
    if not all_weeks:
        return []

    rows = []
    week = date.fromisoformat(all_weeks[0])
    last = date.fromisoformat(all_weeks[-1])
    while week <= last:
        key = week.isoformat()
        row = sessions.get(key)
        rows.append({
            "week_start": key,
            "sessions": row["sessions"] if row else 0,
            "average_mood": row["average_mood"] if row else None,  # None = no sessions that week
            "human_steps_taken": row["human_steps_taken"] if row else 0,
            "safety_events": safety.get(key, 0),
        })
        week += timedelta(days=7)
    return rows
