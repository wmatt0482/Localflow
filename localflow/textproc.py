"""Post-processing of transcribed text: voice commands and replacements."""

from __future__ import annotations

import re

# Spoken command -> replacement. Matched case-insensitively as whole
# phrases, tolerating surrounding punctuation the model may add
# (e.g. "New line." -> newline).
_VOICE_COMMANDS = {
    "new paragraph": "\n\n",
    "new line": "\n",
}


def _command_pattern(phrase: str) -> re.Pattern[str]:
    words = r"[ \t]+".join(re.escape(w) for w in phrase.split())
    # Spaces around the phrase and punctuation attached to it are
    # consumed, so "foo. New line. Bar" becomes "foo.\nBar".
    return re.compile(rf"[ \t]*\b{words}\b[,.!?;:]?[ \t]*", re.IGNORECASE)


_COMMAND_PATTERNS = {
    phrase: _command_pattern(phrase) for phrase in _VOICE_COMMANDS
}


def apply_voice_commands(text: str) -> str:
    # "new paragraph" first so "new line" never partially matches it.
    for phrase in ("new paragraph", "new line"):
        text = _COMMAND_PATTERNS[phrase].sub(_VOICE_COMMANDS[phrase], text)
    return text


def apply_replacements(text: str, replacements: dict[str, str]) -> str:
    """Case-insensitive whole-word replacements from the user's dictionary."""
    for src, dst in replacements.items():
        pattern = re.compile(rf"\b{re.escape(src)}\b", re.IGNORECASE)
        text = pattern.sub(dst, text)
    return text


def process(
    text: str,
    *,
    voice_commands: bool = True,
    replacements: dict[str, str] | None = None,
    trailing_space: bool = False,
) -> str:
    """Full post-processing pipeline applied to each utterance."""
    if replacements:
        text = apply_replacements(text, replacements)
    if voice_commands:
        text = apply_voice_commands(text)
    # Collapse runs of spaces the substitutions may have left behind,
    # but keep newlines intact.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n")).strip()
    if text and trailing_space and not text.endswith("\n"):
        text += " "
    return text
