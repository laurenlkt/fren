"""
Shared test setup. pytest runs this automatically.

1. Every test gets its own throwaway database, so the tests NEVER touch
   your real data/fren.db.
2. The real AI is replaced with fakes, so the normal tests need no API
   key, no internet and cost nothing. Tests marked @pytest.mark.live are
   the exception: they use the real AI (and are skipped unless you ask).
"""

import sys
from pathlib import Path

import pytest

# Let the tests "import config" and "import app" from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from app import ai_client  # noqa: E402

FAKE_REPLY = "Fake AI reply. What would you like to focus on?"


def pytest_configure(config):
    config.addinivalue_line("markers", "live: uses the real AI (costs money)")


def fake_classifier(message):
    return False  # "no crisis" (the keyword check still runs for real)


def fake_generate_reply(stage, mood, transcript):
    return FAKE_REPLY


FAKE_DRAFT = "Hi, I've missed you. Fancy a coffee this week?"


def fake_draft_message(recipient, what_to_say):
    return FAKE_DRAFT


@pytest.fixture(autouse=True)
def temporary_database(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "test.db")
    yield


@pytest.fixture(autouse=True)
def fake_ai(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return  # live tests use the real AI
    monkeypatch.setattr(ai_client, "classify_crisis", fake_classifier)
    monkeypatch.setattr(ai_client, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(ai_client, "draft_message", fake_draft_message)
