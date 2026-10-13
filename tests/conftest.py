"""
Shared test setup. pytest runs this automatically.

It makes sure the tests NEVER touch your real database: every test gets
its own throwaway database file in a temporary folder.
"""

import sys
from pathlib import Path

import pytest

# Let the tests "import config" and "import app" from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402


@pytest.fixture(autouse=True)
def temporary_database(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "test.db")
    yield
