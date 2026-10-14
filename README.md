# Fren

Fren is a research prototype: a wellbeing companion for adult university
students, designed **not** to build dependence. It is **not therapy and not
crisis care**. It is for testing under ethics oversight, not public release.

> **Build status:** Step 6 of 8 is done: the safety layer, the session flow
> with its limits, AI replies inside each stage, the reach-out draft, and
> the taper suggestion and "Looking back" review.

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
python -m pytest tests -v -s -k live
```

`-s` prints each real AI reply so you can read them, not just see pass/fail.
The live tests check the classifier, and that replies to tricky messages
("are you a real person?", "will you miss me?", "do I have depression?")
get through the output filter.

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

Three settings in `config.py` help while you're developing. **Change them
back before any real participant uses Fren.** While any of them is in
developer mode, the server prints a warning and every page shows a red banner.

- `DEV_MODE = True` makes gaps count in minutes instead of hours, so a
  "1 day" gap becomes 24 minutes.
- `USE_AI_CLASSIFIER = False` skips the AI crisis check (keywords still
  run), so you can click through without an API key. Without this, and
  with no key, every message fails safe and shows the help message.
- `USE_AI_REPLIES = False` uses the placeholder replies in
  `content/scripted_replies.json` instead of the AI.

To start again as a brand-new participant, delete the cookie for
127.0.0.1 in your browser, or use a private window.

To wipe all the data, stop the server and delete `data/fren.db`.

---

## Where things are

| What | File |
|---|---|
| Settings (model name, limits, logging) | `config.py` |
| **Fren's rules for the AI (system prompt)** | `content/system_prompt.txt` |
| What the AI is told about each stage | `content/stage_instructions.json` |
| Reply shown if the AI can't reply | `content/ai_unavailable_reply.txt` |
| Instructions for drafting reach-out messages | `content/draft_prompt.txt` |
| Crisis keyword list | `content/crisis_keywords.txt` |
| Crisis classifier prompt | `content/crisis_classifier_prompt.txt` |
| Help message (UK services) | `content/crisis_message.html` |
| Banned AI phrases | `content/banned_output_phrases.txt` |
| Reply shown when an AI reply is blocked | `content/safe_fallback_reply.txt` |
| Crisis check code | `app/safety/crisis_check.py` |
| Output filter code | `app/safety/output_filter.py` |
| Example test messages | `tests/safety_examples.py` |
| Line Fren shows at the start of each stage | `content/stage_prompts.json` |
| Placeholder replies (developer mode only) | `content/scripted_replies.json` |
| The only code that calls the AI | `app/ai_client.py` |
| Text on the session-ended screen | `content/closing_messages.json` |
| The session state machine | `app/session_flow.py` |
| The "suggest a longer gap" rule | `app/taper.py` |
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
  start/end times, why it ended, the plan, whether the human step was
  taken, how many drafts were asked for, and whether "Looking back" was seen.
- If a crisis is detected, the session ends and the help message is shown.

### How each AI reply is made

1. The crisis check runs first. A crisis message never reaches the reply AI.
2. Fren sends the AI: the rules in `system_prompt.txt`, the instructions for
   the **current** stage from `stage_instructions.json` (with the check-in
   mood filled in), and this session's chat so far.
3. The AI writes one short reply. It can't change the stage. Only the app
   moves the session on, by counting messages or when "Move on" is pressed.
4. The reply goes through the output filter. If it fails, the safe fallback
   is shown instead and a safety event is logged.
5. If the AI call fails (no key, no internet, the model declines, the reply
   is cut off), `ai_unavailable_reply.txt` is shown and the session carries on.

### The reach-out step

In the "Reach out" stage, a panel appears under the chat:

1. The participant types **who** they could contact and **roughly what to say**.
2. "Help me draft it" runs the crisis check on what they typed, then asks
   the AI for a short draft in their own voice (`content/draft_prompt.txt`).
   Only those two boxes are sent, not the session chat.
3. The draft goes through the output filter. Diagnosis and medical rules
   apply, but the rules about the AI's own feelings don't, because the
   draft is the participant's words to someone they know ("I've missed you"
   is fine there).
4. The participant edits it, copies it, and sends it themselves. **Fren
   never sends anything and never saves the draft, the name or the request.**
5. They choose: "I've sent it", "I'll get in touch after this session", or
   "Not this time". Only "sent" counts as the human step taken.

Drafts don't use up the 12 messages, but there are at most 3 per session
(`MAX_DRAFTS_PER_SESSION` in `config.py`).

### Looking back, and the longer-gap suggestion

**Looking back** (`/review`): when the gap has passed and the participant
comes back, they see one screen before the check-in. It shows:
- their plan from last time, with a prompt to think about how it went (the
  answer isn't asked for or stored)
- "Did you get in touch?", only if last time they chose "I'll get in touch
  after this session". "Yes" marks the human step as taken for that session.

It's shown once. Starting a new session closes it even if it was skipped.

**Longer gap (taper)**, in `app/taper.py`, with settings in `config.py`:
- Fren looks at the check-in moods of the last 3 finished sessions.
- "Stable or improving" means the mood never drops by more than 1 between
  sessions, and the latest isn't lower than the first. So 3,3,4 and 3,2,3
  count; 4,3,3 and 4,2,4 don't.
- If any of those sessions ended in a crisis, no suggestion is made.
- The suggestion is the next option up (1 day → 2 days → 3 days → 1 week).
  It appears on the close screen and on the "Looking back" screen.
- Yes changes the gap straight away. Either answer stops the question until
  there have been 3 more sessions.

**Data sent to Anthropic:** each participant message goes to the API twice
(the crisis check, then the reply). The reply call also includes the chat so far.
Check Anthropic's current data retention terms for your ethics application.
Participants are told about this on the onboarding page.

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
