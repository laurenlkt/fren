"""
Tests for the session state machine (app/session_flow.py).

`now` lets us pretend time has passed: T0 is "the start", and
T0 + timedelta(minutes=11) is "eleven minutes later".
The crisis classifier is faked so no internet is needed.
"""

from datetime import datetime, timedelta, timezone

import pytest

import config
from app import database, session_flow
from app.session_flow import SessionError

T0 = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def no_crisis(message):
    return False


@pytest.fixture
def user_id():
    database.init_db()
    return database.create_user(min_gap_hours=24)


def send(user_id, text="hello", minutes=1):
    """Send a message `minutes` after T0."""
    return session_flow.handle_message(
        user_id, text, classifier=no_crisis, now=T0 + timedelta(minutes=minutes)
    )


def current_session(user_id):
    return database.get_open_session(user_id) or database.get_last_ended_session(user_id)


# --- Starting a session -----------------------------------------------------
def test_session_starts_at_checkin_with_the_fixed_prompt(user_id):
    session = session_flow.start_session(user_id, mood=3, now=T0)
    assert session["stage"] == "checkin"
    assert session["mood"] == 3
    messages = database.get_messages(session["id"])
    assert messages[0]["role"] == "fren"
    assert messages[0]["text"] == session_flow.stage_prompt("checkin")


@pytest.mark.parametrize("bad_mood", [0, 6, -1, "3", None])
def test_bad_mood_is_rejected(user_id, bad_mood):
    with pytest.raises(SessionError):
        session_flow.start_session(user_id, mood=bad_mood, now=T0)


def test_starting_twice_returns_the_same_open_session(user_id):
    first = session_flow.start_session(user_id, mood=3, now=T0)
    second = session_flow.start_session(user_id, mood=5, now=T0 + timedelta(minutes=1))
    assert first["id"] == second["id"]


def test_unknown_user_cannot_start():
    database.init_db()
    with pytest.raises(SessionError):
        session_flow.start_session("not-a-real-user", mood=3, now=T0)


# --- Stages ---------------------------------------------------------------
def test_stages_follow_the_message_budget(user_id):
    session_flow.start_session(user_id, mood=3, now=T0)
    seen = []
    for _ in range(config.SESSION_MAX_USER_MESSAGES - 1):
        seen.append(database.get_open_session(user_id)["stage"])
        send(user_id)
    # 1 checkin, 3 focus, 3 reflection, 2 plan, 2 human_step
    assert seen == (["checkin"] + ["focus"] * 3 + ["reflection"] * 3
                    + ["plan"] * 2 + ["human_step"] * 2)
    assert database.get_open_session(user_id)["stage"] == "close"


def test_move_on_skips_ahead_and_finishing_close_completes(user_id):
    session_flow.start_session(user_id, mood=3, now=T0)
    for expected in ["focus", "reflection", "plan", "human_step", "close"]:
        session_flow.move_on(user_id, now=T0 + timedelta(minutes=1))
        assert database.get_open_session(user_id)["stage"] == expected
    session_flow.move_on(user_id, now=T0 + timedelta(minutes=2))
    assert database.get_open_session(user_id) is None
    assert current_session(user_id)["end_reason"] == "completed"


# --- The 12 message limit -------------------------------------------------
def test_session_ends_after_12_messages_and_refuses_the_13th(user_id):
    session_flow.start_session(user_id, mood=3, now=T0)
    for _ in range(config.SESSION_MAX_USER_MESSAGES):
        send(user_id)
    session = current_session(user_id)
    assert session["ended_at"] is not None
    assert session["user_message_count"] == 12
    with pytest.raises(SessionError):
        send(user_id)


def test_message_limit_applies_even_after_skipping_stages(user_id):
    # Skip straight to close, then talk: the close stage budget (1) ends it.
    session_flow.start_session(user_id, mood=3, now=T0)
    for _ in range(5):
        session_flow.move_on(user_id, now=T0)
    send(user_id)
    assert current_session(user_id)["end_reason"] == "completed"


# --- The 10 minute limit --------------------------------------------------
def test_message_after_10_minutes_is_refused(user_id):
    session_flow.start_session(user_id, mood=3, now=T0)
    send(user_id, minutes=9)  # fine
    with pytest.raises(SessionError):
        send(user_id, minutes=10)  # exactly 10 minutes: time's up
    session = current_session(user_id)
    assert session["end_reason"] == "time_limit"


def test_abandoned_session_records_the_deadline_as_end_time(user_id):
    session_flow.start_session(user_id, mood=3, now=T0)
    # Participant closes the tab; nobody looks again for 3 hours.
    session_flow.get_status(user_id, now=T0 + timedelta(hours=3))
    ended = database.from_text(current_session(user_id)["ended_at"])
    assert ended == T0 + timedelta(minutes=10)


def test_status_reports_time_and_messages_left(user_id):
    session_flow.start_session(user_id, mood=3, now=T0)
    send(user_id, minutes=1)
    status = session_flow.get_status(user_id, now=T0 + timedelta(minutes=4))
    assert status["open_session"]["seconds_left"] == 6 * 60
    assert status["open_session"]["messages_left"] == 11


# --- The gap between sessions ---------------------------------------------
def test_new_session_refused_until_gap_has_passed(user_id):
    session_flow.start_session(user_id, mood=3, now=T0)
    session_flow.get_status(user_id, now=T0 + timedelta(minutes=10))  # time runs out
    gap_ends = T0 + timedelta(minutes=10) + timedelta(hours=24)

    with pytest.raises(SessionError) as error:
        session_flow.start_session(user_id, mood=4, now=gap_ends - timedelta(minutes=1))
    assert error.value.code == "too_soon"
    assert error.value.extra["next_available_at"] == database.to_text(gap_ends)

    session = session_flow.start_session(user_id, mood=4, now=gap_ends)
    assert session["ended_at"] is None


def test_dev_mode_counts_gap_in_minutes(user_id, monkeypatch):
    monkeypatch.setattr(config, "DEV_MODE", True)
    session_flow.start_session(user_id, mood=3, now=T0)
    session_flow.move_on(user_id, now=T0)
    for _ in range(5):
        session_flow.move_on(user_id, now=T0)  # finish at T0
    # Gap is "24" -> 24 minutes in DEV_MODE
    session_flow.start_session(user_id, mood=3, now=T0 + timedelta(minutes=24))


# --- Safety inside the session --------------------------------------------
def test_crisis_message_ends_session_and_is_not_kept(user_id):
    session_flow.start_session(user_id, mood=2, now=T0)
    result = session_flow.handle_message(
        user_id, "I want to die", classifier=no_crisis, now=T0 + timedelta(minutes=1)
    )
    assert result == {"status": "crisis"}
    session = current_session(user_id)
    assert session["end_reason"] == "crisis"
    with database.get_connection() as connection:
        events = connection.execute("SELECT * FROM safety_events").fetchall()
        kept = connection.execute("SELECT * FROM session_messages").fetchall()
    assert len(events) == 1
    assert kept == []  # the words weren't stored anywhere


def test_classifier_failure_also_ends_session(user_id):
    def broken(message):
        raise TimeoutError()

    session_flow.start_session(user_id, mood=3, now=T0)
    result = session_flow.handle_message(user_id, "hi", classifier=broken, now=T0)
    assert result["status"] == "crisis"


def test_replies_go_through_the_output_filter(user_id, monkeypatch):
    monkeypatch.setattr(session_flow, "scripted_reply", lambda stage, n: "I'll miss you!")
    session_flow.start_session(user_id, mood=3, now=T0)
    result = send(user_id)
    assert "miss you" not in result["reply"]


def test_chat_is_deleted_when_session_ends(user_id):
    session = session_flow.start_session(user_id, mood=3, now=T0)
    send(user_id, "something personal")
    assert len(database.get_messages(session["id"])) > 0
    session_flow.get_status(user_id, now=T0 + timedelta(minutes=11))
    assert database.get_messages(session["id"]) == []


# --- Plans ----------------------------------------------------------------
def test_plan_only_allowed_from_plan_stage(user_id):
    session_flow.start_session(user_id, mood=3, now=T0)
    with pytest.raises(SessionError):
        session_flow.save_plan(user_id, "walk on Tuesday", now=T0)
    for _ in range(3):
        session_flow.move_on(user_id, now=T0)  # -> plan
    session_flow.save_plan(user_id, "walk on Tuesday", now=T0)
    assert database.get_open_session(user_id)["plan_text"] == "walk on Tuesday"


def test_plan_survives_session_end(user_id):
    session_flow.start_session(user_id, mood=3, now=T0)
    for _ in range(3):
        session_flow.move_on(user_id, now=T0)
    session_flow.save_plan(user_id, "call mum", now=T0)
    session_flow.get_status(user_id, now=T0 + timedelta(minutes=11))
    assert current_session(user_id)["plan_text"] == "call mum"


def test_overlong_plan_and_message_are_rejected(user_id):
    session_flow.start_session(user_id, mood=3, now=T0)
    with pytest.raises(SessionError):
        send(user_id, "x" * (config.MAX_MESSAGE_LENGTH + 1))
    for _ in range(3):
        session_flow.move_on(user_id, now=T0)
    with pytest.raises(SessionError):
        session_flow.save_plan(user_id, "x" * (config.MAX_PLAN_LENGTH + 1), now=T0)
