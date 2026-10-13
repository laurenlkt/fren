# Fren

Fren is a research prototype: a wellbeing companion for adult university
students, designed **not** to build dependence. It is **not therapy and not
crisis care**. It is for testing under ethics oversight, not public release.

> **Build status:** Step 2 of 8 is done (the safety layer and its tests).
> There is no AI chat yet.

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

You can edit everything in `content/` without touching any code. Changes
apply on the next message, with no restart needed.

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
