"""Plain-ASCII text cleanup for TTS and stored Reddit comments."""

from __future__ import annotations

import re

# Keep English letters, digits, common punctuation, and whitespace; drop emojis,
# other scripts, ZWJ, variation selectors, etc.
_NON_PLAIN_ENGLISH = re.compile(r"[^a-zA-Z0-9\s.,!?'\-:;()\"/]")


def sanitize_plain_english_tts(text: str) -> str:
    """
    Return plain English text suitable for TTS: strip emojis and any character
    outside a small ASCII whitelist, then collapse whitespace.
    """
    if not text:
        return ""
    cleaned = _NON_PLAIN_ENGLISH.sub("", text)
    cleaned = " ".join(cleaned.split())
    return cleaned.strip()
