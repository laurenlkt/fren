"""
The Fren session "state machine".

A session always moves through the same stages, in order:

    checkin -> focus -> reflection -> plan -> human_step -> close -> (ended)

THIS file decides which stage we're in, when to move on, and when the
session must end. The AI (from step 4) only ever writes ONE reply inside
the current stage. It can never change the stage or extend the session.

The limits are checked here, on the server, on every request:
  - 10 minutes since the session started   (config.SESSION_MAX_MINUTES)
  - 12 participant messages                (config.SESSION_MAX_USER_MESSAGES)
  - a minimum gap before the next session  (chosen by the participant)

Most functions take an optional `now` argument. Normally it's left out and
the real time is used; the tests pass in a pretend time so they can "jump"
ten minutes ahead without actually waiting.
"""

import json
from datetime import timedelta

import config
from app import database
from app.safety import crisis_check, output_filter

ENDED = "ended"  # the stage value once a session has finished


class SessionError(Exception):
    """
    Raised when a request isn't allowed (e.g. a message after the session
    closed). `code` is a short machine-readable name; the text is shown to
    the participant.
    """

    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra  # e.g. next_available_at


# ---------------------------------------------------------------------------
# Reading the editable content files
# ---------------------------------------------------------------------------
def _load_json(filename):
    return json.loads((config.CONTENT_DIR / filename).read_text(encoding="utf-8"))


def stage_prompt(stage):
    """The fixed line Fren shows when a stage begins."""
    return _load_json("stage_prompts.json")[stage]


def scripted_reply(stage, stage_message_number):
    """
    STEP 3 placeholder: pick a pre-written reply.
    In step 4 this is replaced by the AI (still inside the same stage).
    """
    replies = _load_json("scripted_replies.json")[stage]
    index = min(stage_message_number - 1, len(replies) - 1)
    return replies[index]


# ---------------------------------------------------------------------------
# Time and limit helpers
# ---------------------------------------------------------------------------
def _now(now):
    return now if now is not None else database.now_utc()


def session_deadline(session):
    """The moment the session's time runs out."""
    started = database.from_text(session["started_at"])
    return started + timedelta(minutes=config.SESSION_MAX_MINUTES)


def gap_length(user):
    """
    The participant's minimum gap as a timedelta.
    In DEV_MODE the number is read as minutes instead of hours, for testing.
    """
    if config.DEV_MODE:
        return timedelta(minutes=user["min_gap_hours"])
    return timedelta(hours=user["min_gap_hours"])


def next_available_at(user, now=None):
    """
    When this participant may start their next session.
    Returns None if they can start one right now.
    """
    last = database.get_last_ended_session(user["id"])
    if last is None:
        return None
    available = database.from_text(last["ended_at"]) + gap_length(user)
    return available if available > _now(now) else None


def enforce_limits(session, now=None):
    """
    Close the session if its time or message limit has been reached.
    Returns the (possibly updated) session row.

    This runs at the start of EVERY request, so a session can't go over
    its limits even if the participant leaves the page open, or edits the
    page's JavaScript.
    """
    if session is None or session["ended_at"] is not None:
        return session

    if _now(now) >= session_deadline(session):
        return close_session(session, "time_limit", now)

    if session["user_message_count"] >= config.SESSION_MAX_USER_MESSAGES:
        return close_session(session, "message_limit", now)

    return session


# ---------------------------------------------------------------------------
# Changing the session
# ---------------------------------------------------------------------------
def close_session(session, reason, now=None):
    """
    End the session for good, and delete its chat messages.
    Only mood, times, plan and the human step stay in the database.
    """
    ended_at = _now(now)
    if reason == "time_limit":
        # If nobody was around when time ran out, record the real end time
        # (the deadline), not the moment we happened to notice.
        ended_at = min(ended_at, session_deadline(session))

    database.update_session(
        session["id"],
        ended_at=database.to_text(ended_at),
        end_reason=reason,
        stage=ENDED,
    )
    database.delete_messages(session["id"])
    return database.get_session(session["id"])


def advance_stage(session, now=None):
    """
    Move to the next stage. Moving on from the last stage ("close") ends
    the session as completed.
    """
    stage_index = config.STAGES.index(session["stage"])

    if stage_index == len(config.STAGES) - 1:
        return close_session(session, "completed", now)

    new_stage = config.STAGES[stage_index + 1]
    database.update_session(session["id"], stage=new_stage, stage_message_count=0)
    database.add_message(session["id"], "fren", stage_prompt(new_stage))
    return database.get_session(session["id"])


def _get_open_session_or_fail(user_id, now=None):
    """Find the participant's open session, applying the limits first."""
    session = enforce_limits(database.get_open_session(user_id), now)
    if session is None or session["ended_at"] is not None:
        raise SessionError("no_open_session", "This session has ended.")
    return session


# ---------------------------------------------------------------------------
# The actions the web pages can ask for
# ---------------------------------------------------------------------------
def start_session(user_id, mood, now=None):
    """
    Start a new session with the participant's check-in mood.
    If they already have an open session, that one is returned instead
    (so refreshing the page can't create extra sessions).
    """
    user = database.get_user(user_id)
    if user is None:
        raise SessionError("no_user", "Please complete onboarding first.")

    open_session = enforce_limits(database.get_open_session(user_id), now)
    if open_session is not None and open_session["ended_at"] is None:
        return open_session

    if not isinstance(mood, int) or not (config.MOOD_MIN <= mood <= config.MOOD_MAX):
        raise SessionError("bad_mood", "Please choose a mood from the scale.")

    available = next_available_at(user, now)
    if available is not None:
        raise SessionError(
            "too_soon",
            "Your next session isn't available yet.",
            next_available_at=database.to_text(available),
        )

    session_id = database.create_session(user_id, mood, _now(now))
    database.add_message(session_id, "fren", stage_prompt(config.STAGES[0]))
    return database.get_session(session_id)


def handle_message(user_id, text, classifier=None, now=None):
    """
    Handle one participant message. Returns a dict for the web page:
      {"status": "ok", "reply": "..."}       - normal reply
      {"status": "crisis"}                    - crisis detected; show help
    Raises SessionError if the message isn't allowed.
    """
    session = _get_open_session_or_fail(user_id, now)

    text = (text or "").strip()
    if not text:
        raise SessionError("empty", "Please type a message first.")
    if len(text) > config.MAX_MESSAGE_LENGTH:
        raise SessionError(
            "too_long", f"Please keep messages under {config.MAX_MESSAGE_LENGTH} characters."
        )

    # Count the message straight away - every message counts toward the limit.
    user_count = session["user_message_count"] + 1
    stage_count = session["stage_message_count"] + 1
    database.update_session(
        session["id"], user_message_count=user_count, stage_message_count=stage_count
    )

    # --- SAFETY FIRST: crisis check before anything else sees the message ---
    crisis = crisis_check.screen_user_message(user_id, text, classifier)
    if crisis.is_crisis:
        if config.CRISIS_ENDS_SESSION:
            close_session(database.get_session(session["id"]), "crisis", now)
        return {"status": "crisis"}

    database.add_message(session["id"], "user", text)

    # --- The reply, written INSIDE the current stage ---
    reply = scripted_reply(session["stage"], stage_count)  # step 4: AI goes here
    reply = output_filter.screen_ai_reply(user_id, reply).text
    database.add_message(session["id"], "fren", reply)

    # --- Decide what happens next (the app decides, not the AI) ---
    session = database.get_session(session["id"])
    if user_count >= config.SESSION_MAX_USER_MESSAGES:
        close_session(session, "message_limit", now)
    elif stage_count >= config.STAGE_MESSAGE_BUDGET[session["stage"]]:
        advance_stage(session, now)

    return {"status": "ok", "reply": reply}


def move_on(user_id, now=None):
    """The participant pressed "Move on": go to the next stage."""
    session = _get_open_session_or_fail(user_id, now)
    advance_stage(session, now)


def save_plan(user_id, plan_text, now=None):
    """Save the participant's small plan (allowed from the plan stage on)."""
    session = _get_open_session_or_fail(user_id, now)

    if config.STAGES.index(session["stage"]) < config.STAGES.index("plan"):
        raise SessionError("wrong_stage", "The plan comes a little later in the session.")

    plan_text = (plan_text or "").strip()
    if not plan_text:
        raise SessionError("empty", "Please write your plan first.")
    if len(plan_text) > config.MAX_PLAN_LENGTH:
        raise SessionError(
            "too_long", f"Please keep your plan under {config.MAX_PLAN_LENGTH} characters."
        )

    database.update_session(session["id"], plan_text=plan_text)


# ---------------------------------------------------------------------------
# What the web pages need to draw themselves
# ---------------------------------------------------------------------------
def get_status(user_id, now=None):
    """
    Everything the pages need to know about this participant right now.
    """
    user = database.get_user(user_id)
    if user is None:
        raise SessionError("no_user", "Please complete onboarding first.")

    now = _now(now)
    session = enforce_limits(database.get_open_session(user_id), now)
    status = {
        "dev_warnings": dev_warnings(),
        "open_session": None,
        "last_session": None,
        "next_available_at": None,
    }

    if session is not None and session["ended_at"] is None:
        status["open_session"] = _describe_open_session(session, now)
    else:
        available = next_available_at(user, now)
        status["next_available_at"] = database.to_text(available) if available else None
        last = database.get_last_ended_session(user_id)
        if last is not None:
            status["last_session"] = {
                "end_reason": last["end_reason"],
                "closing_message": _load_json("closing_messages.json")[last["end_reason"]],
                "plan_text": last["plan_text"],
            }

    return status


def _describe_open_session(session, now):
    stage = session["stage"]
    seconds_left = (session_deadline(session) - now).total_seconds()
    return {
        "stage": stage,
        "stage_number": config.STAGES.index(stage) + 1,
        "stages": config.STAGES,
        "seconds_left": max(0, int(seconds_left)),
        "messages_left": config.SESSION_MAX_USER_MESSAGES - session["user_message_count"],
        "plan_text": session["plan_text"],
        "transcript": [dict(row) for row in database.get_messages(session["id"])],
    }


def dev_warnings():
    """Warnings shown in a red banner when developer settings are on."""
    warnings = []
    if not config.USE_AI_CLASSIFIER:
        warnings.append("AI crisis classifier is OFF (keywords only). Not for participants.")
    if config.DEV_MODE:
        warnings.append("DEV_MODE is on: session gaps are in minutes. Not for participants.")
    return warnings
