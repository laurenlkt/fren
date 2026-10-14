"""
Tests for the researcher dashboard (/research).

The important promises:
  - It's OFF without RESEARCH_PASSWORD (no default password).
  - The password is checked with a constant-time comparison.
  - It shows aggregates only: never message text, plans or participant IDs.
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import config
from app import database, main, research, session_flow

PASSWORD = "correct horse battery staple"
GOOD_LOGIN = ("researcher", PASSWORD)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("RESEARCH_PASSWORD", PASSWORD)
    database.init_db()
    return TestClient(main.app)


# --- Turned off without a password --------------------------------------------
@pytest.mark.parametrize("value", [None, "", "   "])
@pytest.mark.parametrize("path", ["/research", "/api/research/summary"])
def test_dashboard_is_off_without_a_password(monkeypatch, path, value):
    if value is None:
        monkeypatch.delenv("RESEARCH_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_PASSWORD", value)
    response = TestClient(main.app).get(path, auth=("researcher", ""))
    assert response.status_code == 503


# --- Logging in -----------------------------------------------------------------
@pytest.mark.parametrize("path", ["/research", "/api/research/summary"])
def test_no_login_asks_for_one(client, path):
    response = client.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")


@pytest.mark.parametrize("login", [
    ("researcher", "wrong password"),
    ("researcher", PASSWORD + " "),
    ("someone", PASSWORD),
    ("researcher", ""),
])
def test_wrong_login_is_refused(client, login):
    assert client.get("/api/research/summary", auth=login).status_code == 401


def test_right_login_works_and_is_not_cached(client):
    page = client.get("/research", auth=GOOD_LOGIN)
    assert page.status_code == 200
    assert "Fren research dashboard" in page.text
    data = client.get("/api/research/summary", auth=GOOD_LOGIN)
    assert data.status_code == 200
    assert data.headers["cache-control"] == "no-store"


def test_participant_cookie_does_not_open_the_dashboard(client):
    client.post("/api/onboard", json={"min_gap_hours": 24})
    assert client.get("/api/research/summary").status_code == 401


def test_page_is_not_reachable_through_static(client):
    assert client.get("/static/research.html").status_code == 404


def test_password_check_uses_constant_time_comparison(monkeypatch):
    monkeypatch.setenv("RESEARCH_PASSWORD", PASSWORD)
    calls = []
    real = secrets.compare_digest
    monkeypatch.setattr(secrets, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    assert research.credentials_ok("researcher", PASSWORD)
    assert not research.credentials_ok("nobody", "nope")
    assert len(calls) == 4  # username AND password compared every time


def test_server_only_listens_on_this_computer():
    assert config.HOST == "127.0.0.1"


# --- The numbers ----------------------------------------------------------------
MONDAY = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)  # a Monday


def finish_session(user_id, mood, when, choice=None, plan=None):
    session_flow.start_session(user_id, mood=mood, now=when)
    for _ in range(3):
        session_flow.move_on(user_id, now=when)
    if plan:
        session_flow.save_plan(user_id, plan, now=when)
    session_flow.move_on(user_id, now=when)
    if choice:
        session_flow.record_human_step(user_id, choice, now=when)
    session_flow.move_on(user_id, now=when)
    session_flow.move_on(user_id, now=when)


@pytest.fixture
def seeded(client, monkeypatch):
    """Two participants, sessions across three weeks (the middle one empty)."""
    monkeypatch.setattr(config, "STORE_FLAGGED_TEXT", True)  # worst case for privacy
    a = database.create_user(24)
    b = database.create_user(24)
    finish_session(a, 2, MONDAY, choice="sent", plan="PRIVATE-PLAN-A")
    finish_session(b, 4, MONDAY + timedelta(days=2), choice="later")
    finish_session(a, 5, MONDAY + timedelta(days=14), choice="skipped")
    database.log_safety_event(a, "keyword", "self-harm", text="SECRET-MESSAGE-TEXT")
    return a, b


def test_summary_numbers(seeded, client):
    data = client.get("/api/research/summary", auth=GOOD_LOGIN).json()
    assert data["totals"] == {
        "participants": 2, "sessions": 3, "human_steps_taken": 1, "safety_events": 1,
    }
    weeks = data["weeks"]
    assert [w["week_start"] for w in weeks[:3]] == ["2026-09-07", "2026-09-14", "2026-09-21"]
    assert weeks[0]["sessions"] == 2 and weeks[0]["average_mood"] == 3.0
    assert weeks[1]["sessions"] == 0 and weeks[1]["average_mood"] is None   # empty week kept
    assert weeks[2]["sessions"] == 1 and weeks[2]["average_mood"] == 5.0
    assert data["human_step_choices"] == {"sent": 1, "later": 1, "skipped": 1, "not_answered": 0}
    assert data["safety_by_source"] == [{"source": "keyword", "count": 1}]
    assert data["safety_by_category"] == [{"category": "self-harm", "count": 1}]


def test_summary_never_contains_text_plans_or_ids(seeded, client):
    a, b = seeded
    body = client.get("/api/research/summary", auth=GOOD_LOGIN).text
    for private in ["SECRET-MESSAGE-TEXT", "PRIVATE-PLAN-A", a, b]:
        assert private not in body


def test_summary_with_no_data(client):
    data = client.get("/api/research/summary", auth=GOOD_LOGIN).json()
    assert data["totals"]["sessions"] == 0
    assert data["weeks"] == []
