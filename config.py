"""
Fren settings.

Every value you might want to change lives here, so you never have to dig
through the rest of the code. After changing something, restart the server.

Secrets (the API key, the researcher password) are NOT stored here.
They are read from environment variables - see README.md.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# BASE_DIR is the folder this file lives in (the project root).
BASE_DIR = Path(__file__).resolve().parent
CONTENT_DIR = BASE_DIR / "content"   # editable text files (prompts, messages, lists)
STATIC_DIR = BASE_DIR / "static"     # HTML / CSS / JS for the browser
DATABASE_PATH = BASE_DIR / "data" / "fren.db"

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
# 127.0.0.1 means "this computer only". Other devices on your network
# cannot reach Fren unless you deliberately change this.
HOST = "127.0.0.1"
PORT = 8000

# ---------------------------------------------------------------------------
# AI model
# ---------------------------------------------------------------------------
# Change the model name here. Used for both the crisis classifier and
# (from step 4) the session replies.
MODEL_NAME = "claude-opus-5-5"

# The crisis classifier only has to answer true/false, so it gets a small
# token limit and low "effort" (less thinking, faster and cheaper).
CLASSIFIER_MAX_TOKENS = 1024
CLASSIFIER_EFFORT = "low"

# How long (seconds) to wait for the classifier before giving up.
# If it gives up, Fren FAILS SAFE and shows the help message.
CLASSIFIER_TIMEOUT_SECONDS = 20

# ---------------------------------------------------------------------------
# Safety logging
# ---------------------------------------------------------------------------
# When a safety event happens, Fren always logs: anonymous user ID, time,
# which check fired, and the category (e.g. "self-harm").
# Set this to True ONLY if your ethics approval allows storing the actual
# words the participant typed. Default: False (text is never stored).
STORE_FLAGGED_TEXT = False
