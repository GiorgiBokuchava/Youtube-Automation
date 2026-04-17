"""Plain-text cleanup for English TTS (ASCII-only, no emoji)."""

from __future__ import annotations

import re
import unicodedata


def sanitize_plain_english_tts(text: str) -> str:
    """
    Return *text* reduced to ASCII suitable for English TTS: accents dropped,
    emoji and other non-ASCII removed, whitespace normalized. Empty string if
    nothing printable remains.
    """
    if not text or not str(text).strip():
        return ""

    normalized = unicodedata.normalize("NFKD", str(text))
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")

    # Drop zero-width and similar noise sometimes left in scraped text
    ascii_only = re.sub(r"[\u200b-\u200f\ufeff]", "", ascii_only)

    collapsed = re.sub(r"\s+", " ", ascii_only).strip()
    return collapsed
