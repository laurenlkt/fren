"""
Tests for the crisis check (app/safety/crisis_check.py).

These use FAKE classifiers, so they run without an API key or internet.
The live test at the bottom only runs if you ask for it (see README).
"""

import os

import pytest

import config
from app import database
from app.safety import crisis_check
from tests import safety_examples as ex


# --- Fake classifiers -------------------------------------------------------
def classifier_says_no(message):
    return False


def classifier_says_yes(message):
    return True


def classifier_breaks(message):
    raise ConnectionError("pretend the internet is down")


def classifier_must_not_be_called(message):
    raise AssertionError("The classifier should not run for keyword hits")


# --- Layer 1: keywords ------------------------------------------------------
@pytest.mark.parametrize("message", ex.KEYWORD_CRISIS_MESSAGES)
def test_keyword_layer_catches_crisis(message):
    result = crisis_check.check_message(message, classifier_must_not_be_called)
    assert result.is_crisis
    assert result.source == "keyword"


@pytest.mark.parametrize("message", ex.KEYWORD_SAFE_MESSAGES)
def test_keyword_layer_lets_ordinary_messages_through(message):
    result = crisis_check.check_message(message, classifier_says_no)
    assert not result.is_crisis


@pytest.mark.parametrize("message", ex.KNOWN_FALSE_ALARMS)
def test_known_false_alarms_still_trigger(message):
    result = crisis_check.check_message(message, classifier_says_no)
    assert result.is_crisis


def test_keyword_hit_reports_category():
    result = crisis_check.check_message("I cut myself", classifier_says_no)
    assert result.categories == ("self-harm",)


# --- Layer 2: classifier ----------------------------------------------------
def test_classifier_can_flag_a_message_with_no_keywords():
    result = crisis_check.check_message(
        "I've been giving my things away", classifier_says_yes
    )
    assert result.is_crisis
    assert result.source == "classifier"


def test_classifier_failure_fails_safe():
    result = crisis_check.check_message("I'm fine, just tired", classifier_breaks)
    assert result.is_crisis
    assert result.source == "classifier_error"


def test_empty_message_is_not_a_crisis():
    assert not crisis_check.check_message("   ", classifier_breaks).is_crisis


# --- Logging ----------------------------------------------------------------
def read_events():
    with database.get_connection() as connection:
        return connection.execute("SELECT * FROM safety_events").fetchall()


def test_crisis_is_logged_without_message_text():
    crisis_check.screen_user_message("user-123", "I want to die", classifier_says_no)
    events = read_events()
    assert len(events) == 1
    assert events[0]["user_id"] == "user-123"
    assert events[0]["source"] == "keyword"
    assert events[0]["category"] == "suicide"
    assert events[0]["text"] is None  # the words were NOT stored


def test_text_is_stored_only_if_config_allows(monkeypatch):
    monkeypatch.setattr(config, "STORE_FLAGGED_TEXT", True)
    crisis_check.screen_user_message("user-123", "I want to die", classifier_says_no)
    assert read_events()[0]["text"] == "I want to die"


def test_safe_message_is_not_logged():
    crisis_check.screen_user_message("user-123", "Exams are stressful", classifier_says_no)
    database.init_db()
    assert read_events() == []


def test_crisis_message_has_uk_services():
    html = crisis_check.crisis_message_html()
    for must_include in ["116 123", "111", "85258", "999"]:
        assert must_include in html


# --- Optional LIVE test against the real AI ---------------------------------
# Skipped unless you set FREN_LIVE_TESTS=1 and ANTHROPIC_API_KEY.
live = pytest.mark.skipif(
    not (os.environ.get("FREN_LIVE_TESTS") == "1" and os.environ.get("ANTHROPIC_API_KEY")),
    reason="live AI test: set FREN_LIVE_TESTS=1 and ANTHROPIC_API_KEY to run",
)


@live
@pytest.mark.live
@pytest.mark.parametrize("message", ex.CLASSIFIER_ONLY_CRISIS_MESSAGES)
def test_live_classifier_catches_hidden_crisis(message):
    from app import ai_client
    assert ai_client.classify_crisis(message) is True


@live
@pytest.mark.live
@pytest.mark.parametrize("message", ex.CLASSIFIER_SAFE_MESSAGES)
def test_live_classifier_allows_ordinary_message(message):
    from app import ai_client
    assert ai_client.classify_crisis(message) is False
