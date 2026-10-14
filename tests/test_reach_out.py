"""
Tests for the reach-out step: drafting a message the participant sends
themselves, and recording what they chose to do.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

import config
from app import ai_client, database, session_flow
from app.session_flow import SessionError
from tests.conftest import FAKE_DRAFT

T0 = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
SOON = T0 + timedelta(minutes=2)


@pytest.fixture
def user_id():
    database.init_db()
    return database.create_user(min_gap_hours=24)


def go_to_stage(user_id, stage):
    session_flow.start_session(user_id, mood=3, now=T0)
    while database.get_open_session(user_id)["stage"] != stage:
        session_flow.move_on(user_id, now=T0)


def draft(user_id, recipient="my sister", what="haven't talked in ages, coffee?"):
    return session_flow.draft_reach_out(user_id, recipient, what, now=SOON)


# --- Drafting ---------------------------------------------------------------
def test_draft_works_in_the_reach_out_stage(user_id):
    go_to_stage(user_id, "human_step")
    assert draft(user_id) == {"status": "ok", "draft": FAKE_DRAFT}


@pytest.mark.parametrize("stage", ["checkin", "focus", "reflection", "plan", "close"])
def test_draft_refused_in_other_stages(user_id, stage):
    go_to_stage(user_id, stage)
    with pytest.raises(SessionError):
        draft(user_id)


def test_draft_needs_both_boxes_filled(user_id):
    go_to_stage(user_id, "human_step")
    with pytest.raises(SessionError):
        draft(user_id, recipient="", what="hello")
    with pytest.raises(SessionError):
        draft(user_id, recipient="mum", what="   ")


def test_overlong_draft_request_is_refused(user_id):
    go_to_stage(user_id, "human_step")
    with pytest.raises(SessionError):
        draft(user_id, what="x" * (config.MAX_DRAFT_REQUEST_LENGTH + 1))


def test_drafts_are_capped_but_do_not_use_up_messages(user_id):
    go_to_stage(user_id, "human_step")
    for _ in range(config.MAX_DRAFTS_PER_SESSION):
        draft(user_id)
    with pytest.raises(SessionError) as error:
        draft(user_id)
    assert error.value.code == "draft_limit"
    session = database.get_open_session(user_id)
    assert session["user_message_count"] == 0
    assert session["stage"] == "human_step"  # drafting never moves the stage on


def test_draft_is_never_saved(user_id):
    go_to_stage(user_id, "human_step")
    draft(user_id, recipient="Priya", what="sorry I missed her birthday")
    with database.get_connection() as connection:
        everything = str([dict(r) for r in connection.execute("SELECT * FROM sessions")])
        everything += str([dict(r) for r in connection.execute("SELECT * FROM session_messages")])
    assert "Priya" not in everything
    assert "birthday" not in everything
    assert FAKE_DRAFT not in everything


def test_only_the_reach_out_boxes_are_sent_to_the_ai(user_id, monkeypatch):
    seen = {}
    monkeypatch.setattr(ai_client, "draft_message",
                        lambda r, w: seen.update(recipient=r, what=w) or "Hi!")
    go_to_stage(user_id, "human_step")
    draft(user_id, recipient="mum", what="call at the weekend")
    assert seen == {"recipient": "mum", "what": "call at the weekend"}


# --- Safety -----------------------------------------------------------------
def test_crisis_in_draft_request_ends_session_and_skips_ai(user_id, monkeypatch):
    def must_not_run(recipient, what_to_say):
        raise AssertionError("The AI drafted a message for a crisis request")

    monkeypatch.setattr(ai_client, "draft_message", must_not_run)
    go_to_stage(user_id, "human_step")
    result = draft(user_id, recipient="my friend", what="tell her I want to die")
    assert result == {"status": "crisis"}
    assert database.get_last_ended_session(user_id)["end_reason"] == "crisis"


def test_warm_words_are_allowed_in_drafts(user_id):
    # "I've missed you" would be blocked from the AI talking to the
    # participant, but it's fine in the participant's own message.
    go_to_stage(user_id, "human_step")
    assert "missed you" in draft(user_id)["draft"]


def test_diagnosis_in_a_draft_is_still_blocked_and_logged(user_id, monkeypatch):
    monkeypatch.setattr(ai_client, "draft_message",
                        lambda r, w: "Hi, I think I have depression and should take sertraline.")
    go_to_stage(user_id, "human_step")
    with pytest.raises(SessionError) as error:
        draft(user_id)
    assert error.value.code == "draft_blocked"
    with database.get_connection() as connection:
        event = connection.execute("SELECT * FROM safety_events").fetchone()
    assert event["source"] == "output_filter"


def test_ai_failure_gives_a_clear_error(user_id, monkeypatch):
    def broken(recipient, what_to_say):
        raise TimeoutError()

    monkeypatch.setattr(ai_client, "draft_message", broken)
    go_to_stage(user_id, "human_step")
    with pytest.raises(SessionError) as error:
        draft(user_id)
    assert error.value.code == "draft_failed"


# --- What the participant chose ---------------------------------------------
@pytest.mark.parametrize("choice, taken", [("sent", 1), ("later", 0), ("skipped", 0)])
def test_human_step_choice_is_recorded(user_id, choice, taken):
    go_to_stage(user_id, "human_step")
    session_flow.record_human_step(user_id, choice, now=SOON)
    session = database.get_open_session(user_id)
    assert session["human_step_choice"] == choice
    assert session["human_step_taken"] == taken


def test_choice_can_change_and_be_given_at_close(user_id):
    go_to_stage(user_id, "human_step")
    session_flow.record_human_step(user_id, "later", now=SOON)
    session_flow.move_on(user_id, now=SOON)  # -> close
    session_flow.record_human_step(user_id, "sent", now=SOON)
    assert database.get_open_session(user_id)["human_step_taken"] == 1


def test_choice_refused_before_reach_out_stage(user_id):
    go_to_stage(user_id, "plan")
    with pytest.raises(SessionError):
        session_flow.record_human_step(user_id, "sent", now=SOON)


def test_unknown_choice_refused(user_id):
    go_to_stage(user_id, "human_step")
    with pytest.raises(SessionError):
        session_flow.record_human_step(user_id, "maybe", now=SOON)


def test_choice_survives_session_end(user_id):
    go_to_stage(user_id, "human_step")
    session_flow.record_human_step(user_id, "sent", now=SOON)
    session_flow.get_status(user_id, now=T0 + timedelta(minutes=11))  # time runs out
    assert database.get_last_ended_session(user_id)["human_step_taken"] == 1


# --- Old databases ------------------------------------------------------------
def test_database_from_an_earlier_step_is_upgraded():
    # Make a sessions table WITHOUT the new columns, like step 4 did.
    with database.get_connection() as connection:
        connection.execute(
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY, user_id TEXT, started_at TEXT, "
            "ended_at TEXT, end_reason TEXT, stage TEXT, user_message_count INTEGER DEFAULT 0, "
            "stage_message_count INTEGER DEFAULT 0, mood INTEGER, plan_text TEXT, "
            "human_step_taken INTEGER DEFAULT 0)"
        )
    database.init_db()
    with database.get_connection() as connection:
        columns = [r["name"] for r in connection.execute("PRAGMA table_info(sessions)")]
    assert "human_step_choice" in columns
    assert "draft_count" in columns


# --- The fake AI client: what's sent for a draft ------------------------------
# conftest.py swaps draft_message for a fake in every test. Keep the real
# one here, so this test can run it against a fake Anthropic client instead.
REAL_DRAFT_MESSAGE = ai_client.draft_message


def test_draft_request_uses_the_draft_prompt(monkeypatch):
    from tests.test_ai_replies import FakeClient

    client = FakeClient(text="Hi mum, fancy a call on Sunday?")
    monkeypatch.setattr(ai_client, "get_client", lambda: client)

    text = REAL_DRAFT_MESSAGE("mum", "call on Sunday")
    assert text == "Hi mum, fancy a call on Sunday?"
    assert "help a university student draft a short message" in client.sent["system"]
    assert "<recipient>\nmum\n</recipient>" in client.sent["messages"][0]["content"]
    assert len(client.sent["messages"]) == 1  # no session chat is sent


# --- LIVE test with the real AI -----------------------------------------------
live = pytest.mark.skipif(
    not (os.environ.get("FREN_LIVE_TESTS") == "1" and os.environ.get("ANTHROPIC_API_KEY")),
    reason="live AI test: set FREN_LIVE_TESTS=1 and ANTHROPIC_API_KEY to run",
)


@live
@pytest.mark.live
@pytest.mark.parametrize("recipient, what", [
    ("my older brother", "haven't spoken since summer, want to catch up"),
    ("The university wellbeing service", "struggling to sleep before exams, want to book a chat"),
    ("my personal tutor", "behind on my essay, want to ask about an extension"),
])
def test_live_draft(recipient, what):
    from app.safety import output_filter

    text = ai_client.draft_message(recipient, what)
    print(f"\n  to {recipient!r}: {what!r}\n  -> {text!r}")  # shown with pytest -s
    check = output_filter.check_output(text, output_filter.NOT_CHECKED_FOR_DRAFTS)
    assert not check.blocked, f"Blocked ({check.categories}): {text}"
    assert "fren" not in text.lower()
