from __future__ import annotations

from pathlib import Path
from typing import Optional

from youtube_automation.ai.errors import QuotaExhaustedError
from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest


VIDEO_PROMPT = (
    "Generate a short, funny one-sentence commentary. "
    "Max 12 words. Casual tone. No emojis. No questions."
)


def _post_fallback_prompt(title: str, selftext: str, comments: list[str]) -> str:
    context_lines = [f"Title: {title.strip()}"]
    if selftext.strip():
        context_lines.append(f"Description: {selftext.strip()}")

    if comments:
        context_lines.append("Top comments:")
        for i, c in enumerate(comments[:5], start=1):
            context_lines.append(f"{i}. {c}")

    context = "\n".join(context_lines)

    return (
        "You did NOT see the video. Infer what the clip shows from this Reddit context.\n"
        "Write ONE short, funny one-sentence commentary.\n"
        "Rules: Max 12 words. Casual tone. No emojis. No questions.\n\n"
        f"{context}\n"
    )


def generate_commentary_video_first(
    *,
    video_path: Path,
    title: str,
    selftext: str = "",
    top_comments: Optional[list[str]] = None,
    preferred_video_model: Optional[str] = None,
) -> str:
    """
    Try video-capable generation first (Gemini). If quota exhausted, fall back to text-only
    using title/selftext/top comments.
    """
    top_comments = top_comments or []

    # Tier 1: Video-aware commentary
    try:
        req = TextRequest(video=video_path, text=VIDEO_PROMPT)
        return text_service.generate(req, preferred_model=preferred_video_model)

    except QuotaExhaustedError:
        # Tier 2: Post-context fallback
        prompt = _post_fallback_prompt(title, selftext, top_comments)
        req = TextRequest(text=prompt)
        return text_service.generate(req)

    except Exception:
        # If it's not quota, still attempt a graceful fallback (better than failing)
        prompt = _post_fallback_prompt(title, selftext, top_comments)
        req = TextRequest(text=prompt)
        return text_service.generate(req)
