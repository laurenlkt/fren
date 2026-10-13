"""
Crisis check: runs on EVERY participant message before any AI reply.

Two layers:
  1. Keyword check - fast, predictable, works with no internet.
     Uses content/crisis_keywords.txt.
  2. AI classifier - catches things the list misses
     (e.g. "I've been giving my things away").

The rule is FAIL SAFE: if either layer says "crisis", or the classifier
breaks in any way, the message is treated as a crisis.
"""

from dataclasses import dataclass

import config
from app import ai_client, database
from app.safety.text_utils import find_matches, load_phrase_file

KEYWORDS_FILE = config.CONTENT_DIR / "crisis_keywords.txt"
CRISIS_MESSAGE_FILE = config.CONTENT_DIR / "crisis_message.html"


@dataclass
class CrisisResult:
    """The answer from the crisis check."""
    is_crisis: bool
    source: str = ""       # "keyword", "classifier" or "classifier_error"
    categories: tuple = ()  # e.g. ("self-harm",) - only for keyword hits


def check_message(message, classifier=ai_client.classify_crisis):
    """
    Decide whether a message suggests a crisis. Does NOT log anything.

    `classifier` is the function used for layer 2. Normally it's the real
    AI call; the tests swap in a fake one so they run without the internet.
    """
    if not message or not message.strip():
        return CrisisResult(is_crisis=False)

    # --- Layer 1: keywords ---------------------------------------------
    # The file is re-read every time, so your edits apply immediately.
    keyword_entries = load_phrase_file(KEYWORDS_FILE)
    categories = find_matches(message, keyword_entries)
    if categories:
        # No need to ask the AI - we already know enough to show help.
        return CrisisResult(True, "keyword", tuple(categories))

    # --- Layer 2: AI classifier ----------------------------------------
    try:
        if classifier(message):
            return CrisisResult(True, "classifier")
    except Exception:
        # Anything went wrong (no API key, no internet, odd reply...).
        # We can't be sure the message is safe, so we fail safe.
        return CrisisResult(True, "classifier_error")

    return CrisisResult(is_crisis=False)


def screen_user_message(user_id, message, classifier=ai_client.classify_crisis):
    """
    The function the rest of the app calls: check a message and, if it's a
    crisis, record a safety event. Returns the CrisisResult.
    """
    result = check_message(message, classifier)
    if result.is_crisis:
        database.log_safety_event(
            user_id=user_id,
            source=result.source,
            category=",".join(result.categories) or None,
            text=message,  # only actually saved if config.STORE_FLAGGED_TEXT
        )
    return result


def crisis_message_html():
    """The fixed, human-written help message (read fresh each time)."""
    return CRISIS_MESSAGE_FILE.read_text(encoding="utf-8")
