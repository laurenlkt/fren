"""
Fren web server (FastAPI).

Pages (HTML files in static/):
  /            - sends you to the right page for where you are
  /onboarding  - what Fren is, privacy, limits, choose your gap
  /checkin     - mood scale, starts a session
  /session     - the session itself (chat, plan box, progress bar)
  /close       - session close screen
  /review      - "Looking back" at the last session, before the next check-in
  /settings    - limits, gap between sessions, export / delete my data
  /help        - "Get help now": the fixed crisis message
  /research    - researcher dashboard (password protected, aggregates only)

API (used by the pages' JavaScript, all under /api/...):
  POST /api/onboard           create an anonymous participant
  GET  /api/status            where the participant is right now
  POST /api/session/start     start a session with a mood score
  POST /api/session/message   send a message
  POST /api/session/next      "Move on" to the next stage
  POST /api/session/plan      save the small plan
  POST /api/session/draft     reach-out step: get a draft message
  POST /api/session/human-step  reach-out step: sent / later / skipped
  POST /api/review            finish "Looking back" (did you get in touch?)
  POST /api/taper             yes / no to a suggested longer gap
  GET  /api/settings          current gap and limits
  POST /api/settings/gap      change the gap between sessions
  GET  /api/my-data           download everything Fren holds about me
  POST /api/delete-my-data    permanently delete everything about me

Who is who: at onboarding Fren sets a cookie holding a random anonymous ID.
There are no accounts, names or emails.

Start the server with:  python run.py
"""

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from app import database, research, session_flow
from app.safety import crisis_check
from app.session_flow import SessionError

USER_COOKIE = "fren_user"

app = FastAPI(title="Fren")

# Serve the files in static/ (CSS, JS) under /static/...
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")

# Make sure the database tables exist before any request arrives.
database.init_db()

for warning in session_flow.dev_warnings():
    print(f"\n*** WARNING: {warning} ***\n")

if research.research_password() is None:
    print("\n*** Researcher dashboard is OFF: set the RESEARCH_PASSWORD environment variable to turn it on. ***\n")


# ---------------------------------------------------------------------------
# Errors: turn a SessionError into a clear JSON reply for the page
# ---------------------------------------------------------------------------
@app.exception_handler(SessionError)
def session_error_handler(request, error):
    status_code = 401 if error.code == "no_user" else 409
    return JSONResponse(
        status_code=status_code,
        content={"error": error.code, "message": error.message, **error.extra},
    )


def current_user_id(request):
    """The anonymous ID from the cookie, or None."""
    user_id = request.cookies.get(USER_COOKIE)
    return user_id if database.get_user(user_id) else None


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def page(name):
    return FileResponse(config.STATIC_DIR / f"{name}.html")


@app.get("/")
def home(request: Request):
    user_id = current_user_id(request)
    if user_id is None:
        return RedirectResponse("/onboarding")
    status = session_flow.get_status(user_id)
    if status["open_session"]:
        return RedirectResponse("/session")
    if status["review"]:
        return RedirectResponse("/review")
    return RedirectResponse("/checkin")


@app.get("/onboarding")
def onboarding_page():
    return page("onboarding")


@app.get("/checkin")
def checkin_page():
    return page("checkin")


@app.get("/session")
def session_page():
    return page("session")


@app.get("/close")
def close_page():
    return page("close")


@app.get("/review")
def review_page():
    return page("review")


@app.get("/settings")
def settings_page():
    return page("settings")


@app.get("/help", response_class=HTMLResponse)
def help_page():
    """
    The "Get help now" page. It wraps the editable crisis_message.html in
    a simple page. It deliberately has no AI and no database calls, so it
    works even if everything else is broken.
    """
    message = crisis_check.crisis_message_html()
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fren - Get help now</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <main class="help-page">
    {message}
    <p><a href="/">Back to Fren</a></p>
  </main>
</body>
</html>"""


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
# These small classes describe the JSON each request must send.
# FastAPI checks it automatically and rejects anything else.
class OnboardRequest(BaseModel):
    min_gap_hours: float


class StartRequest(BaseModel):
    mood: int


class MessageRequest(BaseModel):
    text: str


class PlanRequest(BaseModel):
    plan_text: str


class DraftRequest(BaseModel):
    recipient: str
    what_to_say: str


class HumanStepRequest(BaseModel):
    choice: str


class ReviewRequest(BaseModel):
    got_in_touch: bool | None = None   # None = not asked / not answered


class TaperRequest(BaseModel):
    accept: bool


class GapRequest(BaseModel):
    min_gap_hours: float


class DeleteRequest(BaseModel):
    confirm: bool


def require_user(request):
    user_id = current_user_id(request)
    if user_id is None:
        raise SessionError("no_user", "Please complete onboarding first.")
    return user_id


@app.get("/api/config")
def public_config():
    """Settings the onboarding page shows (no secrets here)."""
    return {
        "session_minutes": config.SESSION_MAX_MINUTES,
        "session_messages": config.SESSION_MAX_USER_MESSAGES,
        "gap_choices_hours": config.GAP_CHOICES_HOURS,
        "default_gap_hours": config.DEFAULT_GAP_HOURS,
        "dev_warnings": session_flow.dev_warnings(),
    }


@app.post("/api/onboard")
def onboard(body: OnboardRequest, request: Request):
    if body.min_gap_hours not in config.GAP_CHOICES_HOURS:
        raise SessionError("bad_gap", "Please choose one of the gap options.")

    user_id = current_user_id(request)
    if user_id is None:
        user_id = database.create_user(body.min_gap_hours)
    else:
        database.set_user_gap(user_id, body.min_gap_hours)

    response = JSONResponse({"ok": True})
    response.set_cookie(
        USER_COOKIE,
        user_id,
        max_age=60 * 60 * 24 * 365,  # one year
        httponly=True,                # page scripts can't read it
        samesite="strict",            # other websites can't send it
    )
    return response


@app.get("/api/status")
def status(request: Request):
    return session_flow.get_status(require_user(request))


@app.post("/api/session/start")
def start(body: StartRequest, request: Request):
    session_flow.start_session(require_user(request), body.mood)
    return {"ok": True}


@app.post("/api/session/message")
def message(body: MessageRequest, request: Request):
    result = session_flow.handle_message(require_user(request), body.text)
    if result["status"] == "crisis":
        result["crisis_html"] = crisis_check.crisis_message_html()
    return result


@app.post("/api/session/next")
def next_stage(request: Request):
    session_flow.move_on(require_user(request))
    return {"ok": True}


@app.post("/api/session/plan")
def plan(body: PlanRequest, request: Request):
    session_flow.save_plan(require_user(request), body.plan_text)
    return {"ok": True}


@app.post("/api/session/draft")
def draft(body: DraftRequest, request: Request):
    result = session_flow.draft_reach_out(require_user(request), body.recipient, body.what_to_say)
    if result["status"] == "crisis":
        result["crisis_html"] = crisis_check.crisis_message_html()
    return result


@app.post("/api/session/human-step")
def human_step(body: HumanStepRequest, request: Request):
    session_flow.record_human_step(require_user(request), body.choice)
    return {"ok": True}


@app.post("/api/review")
def review(body: ReviewRequest, request: Request):
    session_flow.complete_review(require_user(request), body.got_in_touch)
    return {"ok": True}


@app.post("/api/taper")
def taper_answer(body: TaperRequest, request: Request):
    session_flow.answer_taper(require_user(request), body.accept)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Settings, export and delete
# ---------------------------------------------------------------------------
@app.get("/api/settings")
def get_settings(request: Request):
    user = database.get_user(require_user(request))
    return {
        "gap_hours": user["min_gap_hours"],
        "gap_choices_hours": config.GAP_CHOICES_HOURS,
        "session_minutes": config.SESSION_MAX_MINUTES,
        "session_messages": config.SESSION_MAX_USER_MESSAGES,
        "dev_warnings": session_flow.dev_warnings(),
    }


@app.post("/api/settings/gap")
def change_gap(body: GapRequest, request: Request):
    user_id = require_user(request)
    if body.min_gap_hours not in config.GAP_CHOICES_HOURS:
        raise SessionError("bad_gap", "Please choose one of the gap options.")
    database.set_user_gap(user_id, body.min_gap_hours)
    return {"ok": True}


@app.get("/api/my-data")
def export_my_data(request: Request):
    data = database.export_user_data(require_user(request))
    data["note"] = (
        "This is everything Fren holds about you. Chat messages are deleted "
        "when each session ends, so only a session that is still open has any."
    )
    return JSONResponse(
        data,
        headers={
            # Makes the browser download it as a file instead of showing it.
            "Content-Disposition": 'attachment; filename="fren-my-data.json"',
            "Cache-Control": "no-store",
        },
    )


@app.post("/api/delete-my-data")
def delete_my_data(body: DeleteRequest, request: Request):
    user_id = require_user(request)
    if not body.confirm:
        raise SessionError("not_confirmed", "Please confirm that you want to delete everything.")
    database.delete_user_data(user_id)
    response = JSONResponse({"ok": True})
    response.delete_cookie(USER_COOKIE)  # this browser forgets the anonymous ID too
    return response


# ---------------------------------------------------------------------------
# Researcher dashboard
# ---------------------------------------------------------------------------
# HTTP Basic login: the browser shows its own username/password box.
# Username: researcher    Password: whatever RESEARCH_PASSWORD is set to.
basic_login = HTTPBasic(auto_error=False)


def require_researcher(credentials: HTTPBasicCredentials | None = Depends(basic_login)):
    if research.research_password() is None:
        # Refuse to run at all without a password. No default password.
        raise HTTPException(
            status_code=503,
            detail="The researcher dashboard is turned off. Set RESEARCH_PASSWORD and restart.",
        )
    if credentials is None or not research.credentials_ok(credentials.username, credentials.password):
        raise HTTPException(
            status_code=401,
            detail="Researcher login needed.",
            headers={"WWW-Authenticate": 'Basic realm="Fren research"'},
        )


# "no-store" asks the browser not to keep a copy of these pages.
NO_STORE = {"Cache-Control": "no-store"}


@app.get("/research", dependencies=[Depends(require_researcher)])
def research_page():
    # Kept outside static/ so it can only be reached through this login.
    return FileResponse(config.BASE_DIR / "private_pages" / "research.html", headers=NO_STORE)


@app.get("/api/research/summary", dependencies=[Depends(require_researcher)])
def research_summary():
    return JSONResponse(research.summary(), headers=NO_STORE)
