# Fren

Fren is a research prototype: a wellbeing companion for adult university
students, designed **not** to build dependence. It is **not therapy and not
crisis care**. It is for testing under ethics oversight, not public release.

> **Build status:** Step 3 of 8 is done: the safety layer, plus the session
> flow with its limits. Fren's replies are still **scripted placeholders**
> (marked `[scripted]`). The AI replies come in step 4.

---

## Setup (once)

You need **Python 3.10 or newer**. Check with `python3 --version`
(on Windows: `python --version`).

```bash
# 1. Go into the project folder
cd fren

# 2. Create a "virtual environment" (a private box for this project's packages)
python3 -m venv .venv

# 3. Switch it on. You'll need to do this every time you open a new terminal.
source .venv/bin/activate          # Mac / Linux
# .venv\Scripts\Activate.ps1       # Windows PowerShell

# 4. Install the packages
pip install -r requirements.txt
```

### Your API key

Fren reads the key from an environment variable called `ANTHROPIC_API_KEY`.
It is never written in the code. Set it in the terminal you'll run Fren from:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."      # Mac / Linux
# $env:ANTHROPIC_API_KEY="sk-ant-..."      # Windows PowerShell
```

This only lasts until you close that terminal. **Never commit your key.**

Without a key, the AI crisis classifier can't run. Fren then **fails safe**:
every message counts as a possible crisis and the help message is shown.

---

## Run the tests

```bash
python -m pytest tests -v
```

The normal tests use a pretend classifier, so they need no key and no
internet. To also test the **real** AI classifier (this costs a few pence):

```bash
export FREN_LIVE_TESTS=1                   # Windows: $env:FREN_LIVE_TESTS="1"
python -m pytest tests -v -k live
```

## Try the safety layer by hand

```bash
python scripts/try_safety.py --offline     # keywords only, no key needed
python scripts/try_safety.py               # keywords + real AI classifier
```

Type a message to test the crisis check. Start with `out:` to test the AI
output filter instead (e.g. `out: I'll miss you!`).

## Run the server

```bash
python run.py
```

Then open <http://127.0.0.1:8000>. The server only listens on your own
computer (`127.0.0.1`). Stop it with **Ctrl+C**.

### Trying a session without waiting or paying

Two settings in `config.py` help while you're developing. **Both must be
`False` for real participants.** While either is on, the server prints a
warning and every page shows a red banner.

- `DEV_MODE = True` makes gaps count in minutes instead of hours, so a
  "1 day" gap becomes 24 minutes.
- `USE_AI_CLASSIFIER = False` skips the AI crisis check (keywords still
  run), so you can click through without an API key. Without this, and
  with no key, every message fails safe and shows the help message.

To start again as a brand-new participant, delete the cookie for
127.0.0.1 in your browser, or use a private window.

To wipe all the data, stop the server and delete `data/fren.db`.

---

## Where things are

| What | File |
|---|---|
| Settings (model name, limits, logging) | `config.py` |
| Crisis keyword list | `content/crisis_keywords.txt` |
| Crisis classifier prompt | `content/crisis_classifier_prompt.txt` |
| Help message (UK services) | `content/crisis_message.html` |
| Banned AI phrases | `content/banned_output_phrases.txt` |
| Reply shown when an AI reply is blocked | `content/safe_fallback_reply.txt` |
| Crisis check code | `app/safety/crisis_check.py` |
| Output filter code | `app/safety/output_filter.py` |
| Example test messages | `tests/safety_examples.py` |
| Line Fren shows at the start of each stage | `content/stage_prompts.json` |
| Placeholder replies (step 3 only) | `content/scripted_replies.json` |
| Text on the session-ended screen | `content/closing_messages.json` |
| The session state machine | `app/session_flow.py` |
| Database code | `app/database.py` |
| Web routes | `app/main.py` |
| Pages | `static/*.html`, `static/session.js` |

You can edit everything in `content/` without touching any code. Changes
apply on the next message, with no restart needed.

## How a session works

```
onboarding ─► check-in (mood 1-5) ─► session ─► close screen
                                       │
     checkin → focus → reflection → plan → human_step → close → ended
        1        3          3         2         2          1      ← messages per stage
```

- The **server** keeps track of the stage. Each stage allows a set number
  of messages (see `STAGE_MESSAGE_BUDGET` in `config.py`), then Fren moves
  on. "Move on" skips ahead early.
- On **every** request the server checks the limits: 10 minutes since the
  start, or 12 messages. When either is reached the session is closed and
  later messages are refused. The countdown on the page is only a display.
- A new session can't start until the participant's chosen gap has passed
  since the last one ended.
- **Chat messages are deleted when the session ends.** What's kept: mood,
  start/end times, why it ended, the plan, and whether the human step was
  taken.
- If a crisis is detected, the session ends and the help message is shown.

## How the safety layer works

```
participant message
   │
   ├─ 1. keyword check ── match? ──► CRISIS
   │
   ├─ 2. AI classifier ── {"crisis": true}, or any error? ──► CRISIS
   │
   └─ otherwise ──► normal session (from step 3)

CRISIS = message is NOT passed on; the fixed help message is shown;
         a safety event is logged (user ID, time, which check, category).

AI reply ──► output filter ── banned phrase? ──► replaced with the safe
                                                  fallback, and logged
```

Message text is **not** stored in the safety log unless you set
`STORE_FLAGGED_TEXT = True` in `config.py` (only do this if your ethics
approval allows it).
