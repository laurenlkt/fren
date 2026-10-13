"""
Output filter: checks every AI reply BEFORE the participant sees it.

If the reply contains anything from content/banned_output_phrases.txt
(claims of feelings, "I'll miss you", diagnoses, medication advice...),
the whole reply is replaced with content/safe_fallback_reply.txt.

We replace the whole reply rather than cutting out the bad sentence,
because a half-edited reply can still carry the wrong meaning.
"""

from dataclasses import dataclass

import config
from app import database
from app.safety.text_utils import find_matches, load_phrase_file

BANNED_FILE = config.CONTENT_DIR / "banned_output_phrases.txt"
FALLBACK_FILE = config.CONTENT_DIR / "safe_fallback_reply.txt"


@dataclass
class FilterResult:
    """The answer from the output filter."""
    text: str             # what the participant will actually see
    blocked: bool         # True if the original reply was replaced
    categories: tuple = ()


def check_output(ai_reply):
    """Check one AI reply. Does NOT log anything."""
    banned_entries = load_phrase_file(BANNED_FILE)
    categories = find_matches(ai_reply, banned_entries)

    # An empty reply is also unusable, so it gets the fallback too.
    if categories or not ai_reply.strip():
        fallback = FALLBACK_FILE.read_text(encoding="utf-8").strip()
        return FilterResult(fallback, True, tuple(categories) or ("empty",))

    return FilterResult(ai_reply, False)


def screen_ai_reply(user_id, ai_reply):
    """
    The function the rest of the app calls: check a reply and log a safety
    event if it had to be blocked. Returns the FilterResult.
    """
    result = check_output(ai_reply)
    if result.blocked:
        database.log_safety_event(
            user_id=user_id,
            source="output_filter",
            category=",".join(result.categories),
            text=ai_reply,  # only actually saved if config.STORE_FLAGGED_TEXT
        )
    return result
