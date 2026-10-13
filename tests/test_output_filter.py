"""Tests for the output filter (app/safety/output_filter.py)."""

import pytest

from app import database
from app.safety import output_filter
from tests import safety_examples as ex


@pytest.mark.parametrize("reply", ex.BANNED_AI_REPLIES)
def test_banned_replies_are_replaced(reply):
    result = output_filter.check_output(reply)
    assert result.blocked
    assert result.text == output_filter.FALLBACK_FILE.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("reply", ex.ALLOWED_AI_REPLIES)
def test_allowed_replies_pass_unchanged(reply):
    result = output_filter.check_output(reply)
    assert not result.blocked
    assert result.text == reply


def test_fallback_itself_passes_the_filter():
    # If the fallback reply contained banned words, we'd have a loop of
    # "safe" replies that aren't safe. Check it never happens.
    fallback = output_filter.FALLBACK_FILE.read_text(encoding="utf-8")
    assert not output_filter.check_output(fallback).blocked


def test_blocked_reply_is_logged_without_text():
    output_filter.screen_ai_reply("user-123", "I'll miss you!")
    with database.get_connection() as connection:
        events = connection.execute("SELECT * FROM safety_events").fetchall()
    assert len(events) == 1
    assert events[0]["source"] == "output_filter"
    assert events[0]["category"] == "claims-feelings"
    assert events[0]["text"] is None
