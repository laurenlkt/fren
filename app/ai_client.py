"""
The only file in Fren that talks to the Anthropic API.

Right now (step 2) it only does one job: the crisis classifier.
The session replies get added here in step 4.

The API key is read automatically by the Anthropic library from the
ANTHROPIC_API_KEY environment variable. It is never written in the code.
"""

import json

import anthropic

import config

# The classifier's instructions live in an editable text file.
CLASSIFIER_PROMPT_FILE = config.CONTENT_DIR / "crisis_classifier_prompt.txt"

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
        _client = anthropic.Anthropic(timeout=config.CLASSIFIER_TIMEOUT_SECONDS)
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
