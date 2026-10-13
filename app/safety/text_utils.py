"""
Small helpers shared by the crisis check and the output filter:
  - normalise(): tidy text up so matching is reliable
  - load_phrase_file(): read one of the editable lists in content/
  - find_matches(): check text against a loaded list
"""

import re
from pathlib import Path


def normalise(text):
    """
    Turn text into a simple, predictable form before matching.

    Example: "I  can’t go ON!!" -> "i can't go on"
    """
    text = text.lower()
    # Phones often type "curly" apostrophes. Make them the plain ' kind.
    text = text.replace("’", "'").replace("‘", "'")
    # Hyphens and underscores become spaces, so "self-harm" == "self harm".
    text = text.replace("-", " ").replace("_", " ")
    # Replace any other punctuation with a space (keep letters, numbers, ').
    text = re.sub(r"[^a-z0-9' ]", " ", text)
    # Collapse runs of spaces into one, and trim the ends.
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_phrase_file(path):
    """
    Read a phrase list file and return a list of (category, pattern) pairs.

    Each pattern is a compiled regular expression ready to search with.
    Plain phrases are turned into "whole words only" patterns, so the
    phrase "die" will not match the word "diet".
    """
    entries = []
    category = "uncategorised"

    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue  # skip blank lines and comments

        if line.startswith("[") and line.endswith("]"):
            category = line[1:-1].strip()  # a new [category] heading
            continue

        if line.startswith("regex:"):
            # An advanced pattern written by hand - use it as it is.
            pattern = re.compile(line[len("regex:"):].strip())
        else:
            # A plain phrase. Normalise it the same way as messages, then
            # escape it (so characters like ' are treated literally) and
            # wrap it in "word boundaries".
            phrase = re.escape(normalise(line))
            pattern = re.compile(r"(?<![a-z0-9'])" + phrase + r"(?![a-z0-9'])")

        entries.append((category, pattern))

    return entries


def find_matches(text, entries):
    """
    Return the list of categories whose patterns appear in the text.
    An empty list means nothing matched.
    """
    clean = normalise(text)
    categories = []
    for category, pattern in entries:
        if pattern.search(clean) and category not in categories:
            categories.append(category)
    return categories
