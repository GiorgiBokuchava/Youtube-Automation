from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from youtube_automation.ai.errors import QuotaExhaustedError
from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest
from youtube_automation.media.video import _comment_is_clean, _word_count
from youtube_automation.utils.text_sanitize import sanitize_plain_english_tts

logger = logging.getLogger(__name__)

_FALLBACK_MAX_WORDS = 12
_SENTENCE_END = re.compile(r"[.!?]+")


def _video_prompt(theme: str) -> str:
    return (
        "Generate a short, one-sentence commentary that matches this theme: "
        f"{theme}.\n"
        "Rules: Max 12 words. Casual tone. No emojis. No questions."
    )


def _is_single_sentence(text: str) -> bool:
    """Return True when *text* contains at most one sentence-ending boundary."""
    # Strip trailing punctuation so "Great shot!" doesn't count as 2 sentences.
    stripped = text.strip().rstrip(".!?")
    return len(_SENTENCE_END.findall(stripped)) < 2


def _pick_plain_text_fallback(
    candidates: list[str],
    *,
    require_single_sentence: bool = False,
) -> str | None:
    """
    Return the first candidate that is:
    - non-empty after plain-English sanitization
    - at most _FALLBACK_MAX_WORDS words
    - passes the banned-word filter
    - (optionally) is a single sentence
    """
    for raw in candidates:
        text = sanitize_plain_english_tts(raw).strip()
        if not text:
            continue
        if _word_count(text) > _FALLBACK_MAX_WORDS:
            continue
        if not _comment_is_clean(text):
            continue
        if require_single_sentence and not _is_single_sentence(text):
            continue
        return text
    return None


def generate_commentary_video_first(
    *,
    video_path: Path,
    title: str,
    selftext: str = "",
    top_comments: Optional[list[str]] = None,
    preferred_video_model: Optional[str] = None,
    theme: str = "funny",
) -> tuple[str, str, bool]:
    """
    Try video-capable generation first (Gemini).  On failure, pick the first
    clean short text from: post title, then top_comments (in order).
    Raises RuntimeError if none qualify.

    Returns:
        (commentary_text, model_used, fallback_occurred)
    """
    top_comments = top_comments or []

    # Tier 1: Video-aware commentary
    try:
        req = TextRequest(video=video_path, text=_video_prompt(theme))
        result = text_service.generate(req, preferred_model=preferred_video_model)
        return result, preferred_video_model or "gemini", False

    except (QuotaExhaustedError, Exception) as primary_exc:
        logger.debug(
            "Video-based commentary failed (%s), falling back to title/comment",
            type(primary_exc).__name__,
        )

    # Tier 2a: Title — must also be a single sentence
    text = _pick_plain_text_fallback([title], require_single_sentence=True)
    if text:
        logger.debug("Using title fallback: %r", text[:60])
        return text, "text_fallback", True

    # Tier 2b: Top comments — word-count + clean filter only (no sentence check)
    text = _pick_plain_text_fallback(top_comments)
    if text:
        logger.debug("Using comment fallback: %r", text[:60])
        return text, "text_fallback", True

    raise RuntimeError(
        "No video commentary available and no clean title/comment to fall back to"
    )
