from __future__ import annotations

from pathlib import Path
from typing import Optional

from youtube_automation.ai.errors import QuotaExhaustedError
from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest


def _video_prompt(theme: str) -> str:
    return (
        "Generate a short, one-sentence commentary that matches this theme: "
        f"{theme}.\n"
        "Rules: Max 12 words. Casual tone. No emojis. No questions."
    )


def _post_fallback_prompt(
    title: str, selftext: str, comments: list[str], theme: str
) -> str:
    context_lines = [f"Title: {title.strip()}"]
    if selftext.strip():
        context_lines.append(f"Description: {selftext.strip()}")

    if comments:
        context_lines.append("Top comments:")
        for i, c in enumerate(comments[:5], start=1):
            context_lines.append(f"{i}. {c}")

    context = "\n".join(context_lines)

    return (
        "You do NOT see the video. You only have partial Reddit context.\n"
        "Assume details are missing and uncertain.\n\n"
        f"Commentary theme: {theme}.\n\n"
        "First, infer ONLY broad themes from obvious keywords "
        "(animals, people, emotions, general situation).\n"
        "Do NOT guess specific actions, outcomes, locations, or events.\n\n"
        "Write ONE short, vague commentary that matches the specified theme "
        "and would fit MANY possible clips.\n"
        "Keep it generic and non-specific.\n\n"
        "Rules:\n"
        "- Max 12 words\n"
        "- Casual tone\n"
        "- No emojis\n"
        "- No questions\n"
        "- No specific actions or detailed descriptions\n\n"
        f"{context}\n"
    )


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
    Try video-capable generation first (Gemini). If quota exhausted, fall back to text-only
    using title/selftext/top comments.

    Returns:
        tuple: (commentary_text, model_used, fallback_occurred)
    """
    top_comments = top_comments or []

    # Tier 1: Video-aware commentary
    try:
        req = TextRequest(video=video_path, text=_video_prompt(theme))
        result = text_service.generate(req, preferred_model=preferred_video_model)
        return result, preferred_video_model or "gemini", False

    except QuotaExhaustedError:
        # Tier 2: Post-context fallback
        prompt = _post_fallback_prompt(title, selftext, top_comments, theme)
        req = TextRequest(text=prompt)
        result = text_service.generate(req)
        return result, "text_fallback", True

    except Exception:
        # If it's not quota, still attempt a graceful fallback (better than failing)
        prompt = _post_fallback_prompt(title, selftext, top_comments, theme)
        req = TextRequest(text=prompt)
        result = text_service.generate(req)
        return result, "text_fallback", True
