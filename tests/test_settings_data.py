"""
Tests for settings, data export and "delete all my data".
"""

import json

import pytest
from fastapi.testclient import TestClient

import config
from app import database, main


def new_participant():
    """A fresh browser (its own cookie jar) that has done onboarding."""
    client = TestClient(main.app)
    assert client.post("/api/onboard", json={"min_gap_hours": 24}).status_code == 200
    return client


def do_a_session(client, plan):
    client.post("/api/session/start", json={"mood": 3})
    for _ in range(3):
        client.post("/api/session/next")                       # -> plan
    client.post("/api/session/plan", json={"plan_text": plan})
    client.post("/api/session/next")                           # -> human_step
    client.post("/api/session/human-step", json={"choice": "sent"})
    client.post("/api/session/next")
    client.post("/api/session/next")                           # ended


def everything_in_the_database():
    """Every value in every table, as one big string."""
    with database.get_connection() as connection:
        text = ""
        for table in ["users", "sessions", "session_messages", "safety_events"]:
            text += str([dict(r) for r in connection.execute(f"SELECT * FROM {table}")])
    return text


@pytest.fixture(autouse=True)
def setup_db():
    database.init_db()


# --- Settings ---------------------------------------------------------------
def test_settings_show_gap_and_limits():
    client = new_participant()
    settings = client.get("/api/settings").json()
    assert settings["gap_hours"] == 24
    assert settings["session_minutes"] == config.SESSION_MAX_MINUTES
    assert settings["session_messages"] == config.SESSION_MAX_USER_MESSAGES


def test_gap_can_be_changed_to_an_allowed_value_only():
    client = new_participant()
    assert client.post("/api/settings/gap", json={"min_gap_hours": 72}).status_code == 200
    assert client.get("/api/settings").json()["gap_hours"] == 72
    assert client.post("/api/settings/gap", json={"min_gap_hours": 0.1}).status_code == 409
    assert client.get("/api/settings").json()["gap_hours"] == 72


def test_settings_need_a_participant():
    assert TestClient(main.app).get("/api/settings").status_code == 401


@pytest.mark.parametrize("path", ["/settings", "/checkin", "/close", "/review", "/session"])
def test_pages_link_to_help_and_settings(path):
    html = TestClient(main.app).get(path).text
    assert 'href="/help"' in html
    if path != "/settings":
        assert 'href="/settings"' in html


# --- Export -----------------------------------------------------------------
def test_export_has_my_data_and_downloads_as_a_file():
    me = new_participant()
    do_a_session(me, "MY-PLAN")
    response = me.get("/api/my-data")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    data = response.json()
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["plan_text"] == "MY-PLAN"
    assert data["sessions"][0]["human_step_taken"] == 1


def test_export_never_includes_someone_else():
    me, other = new_participant(), new_participant()
    do_a_session(me, "MY-PLAN")
    do_a_session(other, "OTHER-PERSONS-PLAN")
    exported = me.get("/api/my-data").text
    assert "MY-PLAN" in exported
    assert "OTHER-PERSONS-PLAN" not in exported


def test_export_includes_my_safety_events():
    me = new_participant()
    me.post("/api/session/start", json={"mood": 2})
    me.post("/api/session/message", json={"text": "I want to die"})
    events = me.get("/api/my-data").json()["safety_events"]
    assert len(events) == 1
    assert events[0]["source"] == "keyword"


# --- Delete -----------------------------------------------------------------
def test_delete_needs_confirmation():
    me = new_participant()
    assert me.post("/api/delete-my-data", json={"confirm": False}).status_code == 409
    assert me.get("/api/settings").status_code == 200  # still there


def test_delete_removes_everything_about_me_only():
    me, other = new_participant(), new_participant()
    do_a_session(me, "MY-PLAN")
    do_a_session(other, "OTHER-PERSONS-PLAN")
    my_id = me.cookies["fren_user"]
    database.log_safety_event(my_id, "keyword", "self-harm")

    assert me.post("/api/delete-my-data", json={"confirm": True}).status_code == 200

    remaining = everything_in_the_database()
    assert my_id not in remaining
    assert "MY-PLAN" not in remaining
    assert "OTHER-PERSONS-PLAN" in remaining          # someone else's data is untouched
    assert other.get("/api/settings").status_code == 200


def test_delete_also_removes_an_open_session_chat(monkeypatch):
    monkeypatch.setattr(config, "USE_AI_REPLIES", False)
    me = new_participant()
    me.post("/api/session/start", json={"mood": 3})
    me.post("/api/session/message", json={"text": "SOMETHING-I-TYPED"})
    assert "SOMETHING-I-TYPED" in everything_in_the_database()
    me.post("/api/delete-my-data", json={"confirm": True})
    assert "SOMETHING-I-TYPED" not in everything_in_the_database()


def test_after_delete_the_browser_is_logged_out():
    me = new_participant()
    response = me.post("/api/delete-my-data", json={"confirm": True})
    assert "fren_user" in response.headers["set-cookie"]   # the cookie is cleared
    assert "fren_user" not in me.cookies
    assert me.get("/api/status").status_code == 401


def test_deleted_words_are_gone_from_the_database_file_itself():
    # Not just hidden from queries: overwritten in the file on disk.
    me = new_participant()
    do_a_session(me, "ZEBRA-UNIQUE-PLAN-WORDS")
    assert b"ZEBRA-UNIQUE-PLAN-WORDS" in config.DATABASE_PATH.read_bytes()
    me.post("/api/delete-my-data", json={"confirm": True})
    assert b"ZEBRA-UNIQUE-PLAN-WORDS" not in config.DATABASE_PATH.read_bytes()


def test_deleted_participant_disappears_from_the_dashboard(monkeypatch):
    monkeypatch.setenv("RESEARCH_PASSWORD", "pw-for-test")
    me = new_participant()
    do_a_session(me, "a plan")
    researcher = TestClient(main.app)
    before = researcher.get("/api/research/summary", auth=("researcher", "pw-for-test")).json()
    me.post("/api/delete-my-data", json={"confirm": True})
    after = researcher.get("/api/research/summary", auth=("researcher", "pw-for-test")).json()
    assert before["totals"]["participants"] == 1 and before["totals"]["sessions"] == 1
    assert after["totals"]["participants"] == 0 and after["totals"]["sessions"] == 0
