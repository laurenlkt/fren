"""
The Fren session "state machine".

A session always moves through the same stages, in order:

    checkin -> focus -> reflection -> plan -> human_step -> close -> (ended)

THIS file decides which stage we're in, when to move on, and when the
session must end. The AI only ever writes ONE reply inside the current
stage. It can never change the stage or extend the session.

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
from app import ai_client, database, taper
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
    A pre-written placeholder reply. Only used when config.USE_AI_REPLIES
    is False (e.g. trying Fren without an API key).
    """
    replies = _load_json("scripted_replies.json")[stage]
    index = min(stage_message_number - 1, len(replies) - 1)
    return replies[index]


def write_reply(session, stage_message_number):
    """
    Get Fren's reply for the current stage: from the AI normally, or a
    placeholder in developer mode. If the AI fails for any reason, a fixed
    "couldn't reply" message is used instead.
    """
    if not config.USE_AI_REPLIES:
        return scripted_reply(session["stage"], stage_message_number)

    transcript = [dict(row) for row in database.get_messages(session["id"])]
    try:
        return ai_client.generate_reply(session["stage"], session["mood"], transcript)
    except Exception as error:
        print(f"AI reply failed: {type(error).__name__}: {error}")  # for you, in the terminal
        return (config.CONTENT_DIR / "ai_unavailable_reply.txt").read_text(encoding="utf-8").strip()


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

    # Starting a new session closes the "look back" for the previous one,
    # even if it was skipped, so it never pops up later out of context.
    last = database.get_last_ended_session(user_id)
    if last is not None and not last["reviewed"]:
        database.update_session(last["id"], reviewed=1)

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
    reply = write_reply(session, stage_count)
    # Every reply passes the output filter before the participant sees it.
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


# The answers a participant can give at the reach-out step.
HUMAN_STEP_CHOICES = ("sent", "later", "skipped")


def draft_reach_out(user_id, recipient, what_to_say, classifier=None, now=None):
    """
    Reach-out step: ask the AI to draft a message the participant can send
    THEMSELVES to a real person or service. Fren never sends anything, and
    the draft is never saved: it only goes back to the participant's page.

    Returns {"status": "ok", "draft": "..."} or {"status": "crisis"}.
    """
    session = _get_open_session_or_fail(user_id, now)

    if session["stage"] != "human_step":
        raise SessionError("wrong_stage", "Drafting a message is part of the reaching-out step.")

    recipient = (recipient or "").strip()
    what_to_say = (what_to_say or "").strip()
    if not recipient or not what_to_say:
        raise SessionError("empty", "Please fill in who it's for and roughly what to say.")
    if len(recipient) > config.MAX_RECIPIENT_LENGTH or len(what_to_say) > config.MAX_DRAFT_REQUEST_LENGTH:
        raise SessionError("too_long", "Please make that a bit shorter.")

    if session["draft_count"] >= config.MAX_DRAFTS_PER_SESSION:
        raise SessionError(
            "draft_limit",
            "That's all the drafts for this session. You can edit the last one "
            "yourself, or write your own.",
        )
    database.update_session(session["id"], draft_count=session["draft_count"] + 1)

    # --- SAFETY FIRST: what they typed gets the same crisis check as chat ---
    crisis = crisis_check.screen_user_message(user_id, f"{recipient}\n{what_to_say}", classifier)
    if crisis.is_crisis:
        if config.CRISIS_ENDS_SESSION:
            close_session(database.get_session(session["id"]), "crisis", now)
        return {"status": "crisis"}

    if not config.USE_AI_REPLIES:
        draft = f"[scripted draft] Hi, I've been meaning to get in touch. {what_to_say}"
    else:
        try:
            draft = ai_client.draft_message(recipient, what_to_say)
        except Exception as error:
            print(f"AI draft failed: {type(error).__name__}: {error}")  # for you, in the terminal
            raise SessionError(
                "draft_failed",
                "Fren couldn't write a draft just now. You could try again, "
                "or write the message in your own words.",
            )

    # Drafts get the output filter too (minus the rules about the AI's own
    # feelings, since the draft is in the participant's voice).
    check = output_filter.screen_ai_reply(
        user_id, draft, skip_categories=output_filter.NOT_CHECKED_FOR_DRAFTS
    )
    if check.blocked:
        raise SessionError(
            "draft_blocked",
            "Fren couldn't write a suitable draft for that. You could try "
            "describing it differently, or write it in your own words.",
        )

    return {"status": "ok", "draft": draft}


def record_human_step(user_id, choice, now=None):
    """
    The participant says what they'll do about reaching out:
      "sent"    - they've sent it (or called, or met)
      "later"   - they plan to send it after the session
      "skipped" - not this time (that's fine; no pressure)
    Only "sent" counts as the human step being taken. In step 6 the review
    asks people who chose "later" whether they did.
    """
    session = _get_open_session_or_fail(user_id, now)

    if config.STAGES.index(session["stage"]) < config.STAGES.index("human_step"):
        raise SessionError("wrong_stage", "This comes a little later in the session.")
    if choice not in HUMAN_STEP_CHOICES:
        raise SessionError("bad_choice", "Please pick one of the options.")

    database.update_session(
        session["id"], human_step_choice=choice, human_step_taken=1 if choice == "sent" else 0
    )


# ---------------------------------------------------------------------------
# Looking back, before the next check-in
# ---------------------------------------------------------------------------
def review_for(user, now=None):
    """
    What the "Looking back" screen shows, or None if there's nothing to
    review. It appears once, when the participant's gap has passed and
    they come back to start a new session.
    """
    if next_available_at(user, now) is not None:
        return None  # still inside the gap
    last = database.get_last_ended_session(user["id"])
    if last is None or last["reviewed"]:
        return None
    return {
        "plan_text": last["plan_text"],
        # Only ask "did you get in touch?" if they said they'd do it later.
        "ask_about_reaching_out": last["human_step_choice"] == "later",
    }


def complete_review(user_id, got_in_touch=None, now=None):
    """
    The participant finished looking back.
    got_in_touch: True / False if they answered "did you get in touch?",
    or None if they weren't asked or didn't answer.
    """
    user = database.get_user(user_id)
    if user is None:
        raise SessionError("no_user", "Please complete onboarding first.")
    if database.get_open_session(user_id) is not None:
        raise SessionError("in_session", "You're in a session right now.")

    last = database.get_last_ended_session(user_id)
    if last is None or last["reviewed"]:
        return  # nothing to do (e.g. pressed twice)

    if got_in_touch is True and last["human_step_choice"] == "later":
        # They did reach out after the session: the human step was taken.
        database.update_session(last["id"], human_step_choice="sent", human_step_taken=1)
    database.update_session(last["id"], reviewed=1)


def answer_taper(user_id, accept):
    """The participant said yes or no to a longer gap."""
    user = database.get_user(user_id)
    if user is None:
        raise SessionError("no_user", "Please complete onboarding first.")
    if database.get_open_session(user_id) is not None:
        raise SessionError("in_session", "You're in a session right now.")
    taper.answer(user, accept)


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
        "review": None,             # the "Looking back" screen, if due
        "taper_suggestion": None,   # a suggested longer gap, if due
        "gap_hours": user["min_gap_hours"],
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
        status["review"] = review_for(user, now)
        status["taper_suggestion"] = taper.suggestion_for(user)

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
        "drafts_left": config.MAX_DRAFTS_PER_SESSION - session["draft_count"],
        "human_step_choice": session["human_step_choice"],
        "transcript": [dict(row) for row in database.get_messages(session["id"])],
    }


def dev_warnings():
    """Warnings shown in a red banner when developer settings are on."""
    warnings = []
    if not config.USE_AI_CLASSIFIER:
        warnings.append("AI crisis classifier is OFF (keywords only). Not for participants.")
    if not config.USE_AI_REPLIES:
        warnings.append("AI replies are OFF (placeholder replies). Not for participants.")
    if config.DEV_MODE:
        warnings.append("DEV_MODE is on: session gaps are in minutes. Not for participants.")
    return warnings
