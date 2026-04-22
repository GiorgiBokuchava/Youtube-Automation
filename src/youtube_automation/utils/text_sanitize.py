"""Text helpers for TTS and on-screen overlays."""

from __future__ import annotations

import re


def sanitize_plain_english_tts(text: str) -> str:
    """
    Keep ASCII-only text suitable for English TTS (strips emojis and most symbols).
    Used for commentary and Reddit comment context fed to the AI/TTS path.
    """
    if not text:
        return ""
    # Collapse non-ASCII runs to a single space, trim whitespace
    ascii_only = re.sub(r"[^\x00-\x7F]+", " ", text)
    return re.sub(r"\s+", " ", ascii_only).strip()


def truncate_preserve_unicode(text: str, max_len: int, *, suffix: str = "...") -> str:
    """Truncate a string without stripping emojis or non-Latin scripts."""
    if not text or max_len <= 0:
        return ""
    t = text.strip()
    if len(t) <= max_len:
        return t
    if len(suffix) >= max_len:
        return t[:max_len]
    return t[: max_len - len(suffix)].rstrip() + suffix
