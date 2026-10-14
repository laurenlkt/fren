"""
Tests for the taper logic (app/taper.py) and the "Looking back" review.
"""

from datetime import datetime, timedelta, timezone

import pytest

import config
from app import database, session_flow, taper
from app.session_flow import SessionError

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


# --- The mood rule on its own -----------------------------------------------
@pytest.mark.parametrize("moods, expected", [
    ([3, 3, 3], True),    # stable
    ([2, 3, 4], True),    # improving
    ([3, 2, 3], True),    # small dip, back up
    ([1, 1, 1], True),    # stable, but low (see README: your call)
    ([4, 3, 3], False),   # ended lower than it started
    ([4, 2, 4], False),   # dropped by 2 in one step
    ([5, 4, 3], False),   # sliding down
    ([3, 3], False),      # not enough sessions yet
])
def test_stable_or_improving(moods, expected):
    assert taper.mood_is_stable_or_improving(moods) is expected


@pytest.mark.parametrize("current, expected", [(24, 48), (48, 72), (72, 168), (168, None)])
def test_next_longer_gap(current, expected):
    assert taper.next_longer_gap(current) == expected


# --- Helpers that run real sessions -----------------------------------------
@pytest.fixture
def user_id():
    database.init_db()
    return database.create_user(min_gap_hours=24)


def run_sessions(user_id, moods, start=T0, end_reason="completed"):
    """Run one quick session per mood, 8 days apart (longer than any gap). Returns the next free time."""
    when = start
    for mood in moods:
        session_flow.start_session(user_id, mood=mood, now=when)
        if end_reason == "crisis":
            session_flow.handle_message(user_id, "I want to die", now=when)
        else:
            for _ in range(6):
                session_flow.move_on(user_id, now=when)  # finish straight away
        when += timedelta(days=8)
    return when


def suggestion(user_id):
    return taper.suggestion_for(database.get_user(user_id))


# --- When the suggestion appears --------------------------------------------
def test_suggested_after_three_steady_sessions(user_id):
    run_sessions(user_id, [3, 3, 4])
    assert suggestion(user_id) == {"current_hours": 24, "suggested_hours": 48}


def test_not_suggested_after_two(user_id):
    run_sessions(user_id, [3, 4])
    assert suggestion(user_id) is None


def test_not_suggested_when_mood_drops(user_id):
    run_sessions(user_id, [4, 3, 2])
    assert suggestion(user_id) is None


def test_never_suggested_if_a_recent_session_was_a_crisis(user_id):
    when = run_sessions(user_id, [3, 3])
    run_sessions(user_id, [3], start=when, end_reason="crisis")
    assert suggestion(user_id) is None


def test_not_suggested_at_the_longest_gap(user_id):
    database.set_user_gap(user_id, 168)
    run_sessions(user_id, [3, 3, 3])
    assert suggestion(user_id) is None


# --- Answering it -----------------------------------------------------------
def test_accepting_makes_the_gap_longer(user_id):
    when = run_sessions(user_id, [3, 3, 3])
    session_flow.answer_taper(user_id, accept=True)
    assert database.get_user(user_id)["min_gap_hours"] == 48
    assert suggestion(user_id) is None
    # The longer gap applies straight away to the next session.
    last_end = database.from_text(database.get_last_ended_session(user_id)["ended_at"])
    assert session_flow.next_available_at(database.get_user(user_id), now=last_end) == \
        last_end + timedelta(hours=48)


def test_declining_keeps_the_gap_and_stops_asking(user_id):
    run_sessions(user_id, [3, 3, 3])
    session_flow.answer_taper(user_id, accept=False)
    assert database.get_user(user_id)["min_gap_hours"] == 24
    assert suggestion(user_id) is None


def test_asked_again_only_after_three_new_steady_sessions(user_id):
    when = run_sessions(user_id, [3, 3, 3])
    session_flow.answer_taper(user_id, accept=False)
    when = run_sessions(user_id, [3, 3], start=when)
    assert suggestion(user_id) is None          # only 2 new sessions
    run_sessions(user_id, [3], start=when)
    assert suggestion(user_id) is not None      # 3 new steady sessions


def test_answering_with_no_suggestion_does_nothing(user_id):
    run_sessions(user_id, [3])
    session_flow.answer_taper(user_id, accept=True)
    assert database.get_user(user_id)["min_gap_hours"] == 24


def test_cannot_answer_taper_mid_session(user_id):
    when = run_sessions(user_id, [3, 3, 3])
    session_flow.start_session(user_id, mood=3, now=when)
    with pytest.raises(SessionError):
        session_flow.answer_taper(user_id, accept=True)


def test_status_includes_the_suggestion(user_id):
    when = run_sessions(user_id, [3, 3, 3])
    status = session_flow.get_status(user_id, now=when)
    assert status["taper_suggestion"]["suggested_hours"] == 48


# --- Looking back -----------------------------------------------------------
def end_session_with(user_id, plan=None, choice=None, when=T0):
    session_flow.start_session(user_id, mood=3, now=when)
    for _ in range(3):
        session_flow.move_on(user_id, now=when)          # -> plan
    if plan:
        session_flow.save_plan(user_id, plan, now=when)
    session_flow.move_on(user_id, now=when)              # -> human_step
    if choice:
        session_flow.record_human_step(user_id, choice, now=when)
    session_flow.move_on(user_id, now=when)              # -> close
    session_flow.move_on(user_id, now=when)              # -> ended
    return when + timedelta(days=2)                      # after the 24h gap


def test_no_review_before_the_first_session(user_id):
    assert session_flow.get_status(user_id, now=T0)["review"] is None


def test_no_review_while_still_inside_the_gap(user_id):
    end_session_with(user_id, plan="walk")
    assert session_flow.get_status(user_id, now=T0 + timedelta(hours=1))["review"] is None


def test_review_shows_plan_after_the_gap(user_id):
    later = end_session_with(user_id, plan="Library on Tuesday")
    review = session_flow.get_status(user_id, now=later)["review"]
    assert review == {"plan_text": "Library on Tuesday", "ask_about_reaching_out": False}


def test_review_asks_about_reaching_out_only_if_they_said_later(user_id):
    later = end_session_with(user_id, choice="later")
    assert session_flow.get_status(user_id, now=later)["review"]["ask_about_reaching_out"]


def test_saying_yes_marks_the_human_step_taken(user_id):
    later = end_session_with(user_id, choice="later")
    session_flow.complete_review(user_id, got_in_touch=True, now=later)
    last = database.get_last_ended_session(user_id)
    assert last["human_step_taken"] == 1
    assert last["human_step_choice"] == "sent"
    assert session_flow.get_status(user_id, now=later)["review"] is None  # shown once


def test_saying_not_yet_changes_nothing(user_id):
    later = end_session_with(user_id, choice="later")
    session_flow.complete_review(user_id, got_in_touch=False, now=later)
    last = database.get_last_ended_session(user_id)
    assert last["human_step_taken"] == 0
    assert last["human_step_choice"] == "later"


def test_yes_is_ignored_if_they_were_not_asked(user_id):
    later = end_session_with(user_id, choice="skipped")
    session_flow.complete_review(user_id, got_in_touch=True, now=later)
    assert database.get_last_ended_session(user_id)["human_step_taken"] == 0


def test_skipping_the_review_by_starting_a_session_closes_it(user_id):
    later = end_session_with(user_id, plan="walk")
    session_flow.start_session(user_id, mood=4, now=later)
    first = database.get_recent_ended_sessions(user_id, 1)[0]
    assert first["reviewed"] == 1


# --- Via the web API ----------------------------------------------------------
def test_api_review_and_taper(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main

    database.init_db()
    client = TestClient(main.app)
    client.post("/api/onboard", json={"min_gap_hours": 24})
    assert client.post("/api/review", json={}).status_code == 200      # nothing to review: fine
    assert client.post("/api/taper", json={"accept": True}).status_code == 200
    assert client.post("/api/taper", json={}).status_code == 422       # accept is required
    assert 'href="/help"' in client.get("/review").text
