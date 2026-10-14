"""
The only file in Fren that talks to the Anthropic API.

It does two jobs:
  - classify_crisis(): the AI half of the crisis check
  - generate_reply():  Fren's reply inside the current session stage

The API key is read automatically by the Anthropic library from the
ANTHROPIC_API_KEY environment variable. It is never written in the code.
"""

import json

import anthropic

import config

# The instructions for the AI live in editable files in content/.
CLASSIFIER_PROMPT_FILE = config.CONTENT_DIR / "crisis_classifier_prompt.txt"
SYSTEM_PROMPT_FILE = config.CONTENT_DIR / "system_prompt.txt"
STAGE_INSTRUCTIONS_FILE = config.CONTENT_DIR / "stage_instructions.json"

# This "schema" forces the model to reply with exactly {"crisis": true/false}
# and nothing else. It's called "structured output".
CRISIS_SCHEMA = {
    "type": "object",
    "properties": {"crisis": {"type": "boolean"}},
    "required": ["crisis"],
    "additionalProperties": False,
}

_client = None  # created the first time it's needed


def get_client():
    """Create the Anthropic client once and reuse it."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(timeout=config.AI_TIMEOUT_SECONDS)
    return _client


def classify_crisis(message):
    """
    Ask the AI whether a message suggests a crisis.

    Returns True or False.
    Raises an exception if anything goes wrong (no key, network error,
    strange reply...). The caller treats ANY exception as "crisis", so
    a failure here can never let a risky message slip through.
    """
    system_prompt = CLASSIFIER_PROMPT_FILE.read_text(encoding="utf-8")

    response = get_client().beta.messages.create(
        model=config.MODEL_NAME,
        max_tokens=config.CLASSIFIER_MAX_TOKENS,
        system=system_prompt,
        messages=[
            {"role": "user", "content": f"<message>\n{message}\n</message>"}
        ],
        output_config={
            "effort": config.CLASSIFIER_EFFORT,
            "format": {"type": "json_schema", "schema": CRISIS_SCHEMA},
        },
        # If the model declines to answer (it can do this with upsetting
        # text), the API automatically retries on a suitable other model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    # A refusal means we didn't get an answer. Raise so the caller fails safe.
    if response.stop_reason == "refusal":
        raise RuntimeError("Classifier declined to answer")

    # Find the text part of the reply and read the JSON out of it.
    text = next(block.text for block in response.content if block.type == "text")
    result = json.loads(text)

    if not isinstance(result.get("crisis"), bool):
        raise ValueError(f"Unexpected classifier reply: {text!r}")

    return result["crisis"]


# ---------------------------------------------------------------------------
# Session replies
# ---------------------------------------------------------------------------
def build_system_prompt(stage, mood):
    """
    Fren's fixed rules (system_prompt.txt) plus what the CURRENT stage is
    for (stage_instructions.json). The app chooses the stage; the AI is only
    told about it.
    """
    rules = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    stage_instructions = json.loads(STAGE_INSTRUCTIONS_FILE.read_text(encoding="utf-8"))
    stage_text = stage_instructions[stage].replace("{mood}", str(mood))
    return rules + "\n\n" + stage_text


def build_messages(transcript):
    """
    Turn the session transcript into the format the API expects.

    transcript: a list of {"role": "user" or "fren", "text": "..."}.

    The API wants "user" and "assistant" roles, wants the conversation to
    start with the user, and works best when the roles take turns. Fren's
    transcript starts with Fren's opening line, and sometimes has two Fren
    lines in a row (a reply, then the next stage's opening line), so we
    tidy it up here.
    """
    messages = []
    for item in transcript:
        role = "user" if item["role"] == "user" else "assistant"
        if messages and messages[-1]["role"] == role:
            # Same speaker twice in a row: join into one message.
            messages[-1]["content"] += "\n\n" + item["text"]
        else:
            messages.append({"role": role, "content": item["text"]})

    if messages and messages[0]["role"] == "assistant":
        # Put a short note first, so the conversation starts with "user".
        messages.insert(0, {"role": "user", "content": "(The participant has started a Fren session.)"})

    return messages


def generate_reply(stage, mood, transcript):
    """
    Ask the AI for ONE reply inside the current stage.

    Returns the reply text. Raises an exception if anything goes wrong
    (the caller then shows a fixed "couldn't reply" message instead).
    The reply is NOT safety-checked here: the caller always runs it
    through the output filter before the participant sees it.
    """
    messages = build_messages(transcript)
    if not messages or messages[-1]["role"] != "user":
        raise ValueError("The last message must be from the participant")

    response = get_client().beta.messages.create(
        model=config.MODEL_NAME,
        max_tokens=config.REPLY_MAX_TOKENS,
        system=build_system_prompt(stage, mood),
        messages=messages,
        output_config={"effort": config.REPLY_EFFORT},
        # If the model declines to answer, the API retries on a suitable model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("The model declined to reply")
    if response.stop_reason == "max_tokens":
        # The reply was cut off part-way. Better to show nothing than half.
        raise RuntimeError("The reply was too long and got cut off")

    # The response can contain "thinking" parts too; we only want the text.
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise RuntimeError("The model returned an empty reply")
    return text
