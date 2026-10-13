"""
Tests for the web API (app/main.py), using FastAPI's built-in test client.
This acts like a browser: it keeps the cookie between requests.
"""

import pytest
from fastapi.testclient import TestClient

from app import ai_client, main


@pytest.fixture
def client(monkeypatch):
    # Pretend the AI classifier always says "no crisis" (no internet needed).
    monkeypatch.setattr(ai_client, "classify_crisis", lambda message: False)
    main.database.init_db()
    return TestClient(main.app)


def onboard(client):
    response = client.post("/api/onboard", json={"min_gap_hours": 24})
    assert response.status_code == 200


def test_home_sends_new_visitors_to_onboarding(client):
    response = client.get("/", follow_redirects=False)
    assert response.headers["location"] == "/onboarding"


def test_api_needs_onboarding_first(client):
    assert client.get("/api/status").status_code == 401


def test_cookie_is_http_only_and_strict(client):
    response = client.post("/api/onboard", json={"min_gap_hours": 24})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie


def test_gap_must_be_one_of_the_choices(client):
    assert client.post("/api/onboard", json={"min_gap_hours": 0.01}).status_code == 409


def test_full_happy_path(client):
    onboard(client)
    assert client.post("/api/session/start", json={"mood": 4}).status_code == 200

    reply = client.post("/api/session/message", json={"text": "Bit tired today"}).json()
    assert reply["status"] == "ok"

    status = client.get("/api/status").json()
    assert status["open_session"]["stage"] == "focus"
    assert status["open_session"]["messages_left"] == 11


def test_crisis_returns_the_fixed_help_message(client):
    onboard(client)
    client.post("/api/session/start", json={"mood": 2})
    reply = client.post("/api/session/message", json={"text": "I want to kill myself"}).json()
    assert reply["status"] == "crisis"
    assert "116 123" in reply["crisis_html"]
    # And the session is over: further messages are refused.
    assert client.post("/api/session/message", json={"text": "hello"}).status_code == 409


def test_no_second_session_straight_after_one_ends(client):
    onboard(client)
    client.post("/api/session/start", json={"mood": 3})
    for _ in range(6):
        client.post("/api/session/next")  # skip to the end
    response = client.post("/api/session/start", json={"mood": 3})
    assert response.status_code == 409
    assert response.json()["error"] == "too_soon"


@pytest.mark.parametrize("path", ["/onboarding", "/checkin", "/session", "/close"])
def test_every_page_has_the_help_button(client, path):
    html = client.get(path).text
    assert 'href="/help"' in html
