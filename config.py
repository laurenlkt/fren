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

# ---------------------------------------------------------------------------
# Session limits (enforced by the backend, not the browser)
# ---------------------------------------------------------------------------
SESSION_MAX_MINUTES = 10
SESSION_MAX_USER_MESSAGES = 12

# The fixed order of stages. The app moves through these; the AI never can.
STAGES = ["checkin", "focus", "reflection", "plan", "human_step", "close"]

# How many participant messages each stage allows before Fren moves on.
# These add up to 12. The participant can also press "Move on" early.
STAGE_MESSAGE_BUDGET = {
    "checkin": 1,
    "focus": 3,
    "reflection": 3,
    "plan": 2,
    "human_step": 2,
    "close": 1,
}

# Longest message a participant can send (characters).
MAX_MESSAGE_LENGTH = 1000
MAX_PLAN_LENGTH = 500

# If a crisis is detected mid-session, end the session (the participant
# sees the help message instead). Recommended: True.
CRISIS_ENDS_SESSION = True

# ---------------------------------------------------------------------------
# Gap between sessions
# ---------------------------------------------------------------------------
# The participant picks one of these minimum gaps (in hours) at onboarding.
GAP_CHOICES_HOURS = [24, 48, 72, 168]   # 1 day, 2 days, 3 days, 1 week
DEFAULT_GAP_HOURS = 24

# Mood scale used at check-in: 1 = very low ... 5 = very good.
MOOD_MIN = 1
MOOD_MAX = 5

# ---------------------------------------------------------------------------
# Developer settings - MUST be False for real participants
# ---------------------------------------------------------------------------
# DEV_MODE: gaps count in MINUTES instead of hours, so you can test the gap
# without waiting a day (a "24 hour" gap becomes 24 minutes).
DEV_MODE = False

# USE_AI_CLASSIFIER: set to False ONLY to try the app without an API key.
# The keyword check still runs, but the AI check is skipped. The server
# prints a warning and every page shows a red banner while this is off.
USE_AI_CLASSIFIER = True
