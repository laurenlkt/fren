"""
Taper logic: when things seem steady, Fren suggests a LONGER gap between
sessions. This is one of the ways Fren tries not to become something people
depend on.

The rule (settings in config.py):
  - Look at the check-in moods of the last TAPER_SESSIONS finished sessions.
  - "Stable or improving" means the mood never drops by more than
    TAPER_MAX_DROP from one session to the next, AND the latest mood is not
    lower than the first one.
      e.g. 3, 3, 4  -> yes      3, 2, 3 -> yes
           4, 3, 3  -> no (ended lower)    4, 2, 4 -> no (dropped by 2)
  - If any of those sessions ended because of a crisis, never suggest it.
  - The suggestion is the next longer option in GAP_CHOICES_HOURS.
  - It's only a suggestion. Once answered (yes or no), Fren waits for
    another TAPER_SESSIONS new sessions before asking again.
"""

import config
from app import database


def mood_is_stable_or_improving(moods):
    """
    `moods` is a list in time order, oldest first, e.g. [3, 3, 4].
    Returns True if it counts as stable or improving.
    """
    if len(moods) < config.TAPER_SESSIONS:
        return False
    for earlier, later in zip(moods, moods[1:]):
        if later < earlier - config.TAPER_MAX_DROP:
            return False
    return moods[-1] >= moods[0]


def next_longer_gap(current_hours):
    """The next option up in GAP_CHOICES_HOURS, or None if already at the top."""
    longer = [hours for hours in config.GAP_CHOICES_HOURS if hours > current_hours]
    return min(longer) if longer else None


def suggestion_for(user):
    """
    Should Fren suggest a longer gap to this user right now?
    Returns {"current_hours": 24, "suggested_hours": 48} or None.
    """
    recent = database.get_recent_ended_sessions(user["id"], config.TAPER_SESSIONS)
    if len(recent) < config.TAPER_SESSIONS:
        return None

    if any(session["end_reason"] == "crisis" for session in recent):
        return None

    # Already answered a suggestion after one of these sessions? Then wait
    # until there are TAPER_SESSIONS completely new sessions.
    answered_after = user["taper_answered_session_id"]
    if answered_after is not None and any(s["id"] <= answered_after for s in recent):
        return None

    moods = [session["mood"] for session in reversed(recent)]  # oldest first
    if not mood_is_stable_or_improving(moods):
        return None

    suggested = next_longer_gap(user["min_gap_hours"])
    if suggested is None:
        return None

    return {"current_hours": user["min_gap_hours"], "suggested_hours": suggested}


def answer(user, accept):
    """
    The participant answered the suggestion. If they said yes, their gap
    becomes the suggested one. Either way, don't ask again for a while.
    """
    suggestion = suggestion_for(user)
    if suggestion is None:
        return False  # nothing to answer (e.g. a double click)

    if accept:
        database.set_user_gap(user["id"], suggestion["suggested_hours"])
    latest = database.get_last_ended_session(user["id"])
    database.set_taper_answered(user["id"], latest["id"])
    return True
