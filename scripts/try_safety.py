"""
Try the safety layer by hand, in the terminal.

    python scripts/try_safety.py           # keywords + real AI classifier
    python scripts/try_safety.py --offline # keywords only (no API key needed)

Type a message and see what the crisis check decides. Type "out:" before a
message to test the OUTPUT filter instead, e.g.  out: I'll miss you!
Press Enter on an empty line to quit.

Nothing typed here is logged to the database.
"""

import sys
from pathlib import Path

# Let this script import the Fren code from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ai_client  # noqa: E402
from app.safety import crisis_check, output_filter  # noqa: E402


def offline_classifier(message):
    return False  # pretend the AI always says "no crisis"


def main():
    offline = "--offline" in sys.argv
    classifier = offline_classifier if offline else ai_client.classify_crisis
    print("Fren safety tester", "(OFFLINE: keywords only)" if offline else "")

    while True:
        text = input("\n> ").strip()
        if not text:
            break

        if text.startswith("out:"):
            result = output_filter.check_output(text[4:].strip())
            if result.blocked:
                print(f"BLOCKED ({', '.join(result.categories)}). Shown instead:")
                print(f"  {result.text}")
            else:
                print("Allowed.")
            continue

        result = crisis_check.check_message(text, classifier)
        if result.is_crisis:
            detail = f" - {', '.join(result.categories)}" if result.categories else ""
            print(f"CRISIS (detected by: {result.source}{detail})")
        else:
            print("No crisis detected.")


if __name__ == "__main__":
    main()
