from __future__ import annotations

import logging
import re

from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest
from youtube_automation.media.shorts_sourcing import overlay_line_max_chars

logger = logging.getLogger(__name__)


def normalize_short_caption(text: str, *, max_words: int = 5) -> str:
    words = [w for w in (text or "").strip().replace("\n", " ").split() if w]
    if not words:
        return ""
    if max_words > 0 and len(words) > max_words:
        words = words[:max_words]
    return " ".join(words)


def _fit_caption_to_line(
    text: str, *, rank: int, max_words: int, max_line_chars: int
) -> str:
    """Trim to word budget, then shrink words until line fits (prefix + body)."""
    prefix = f"{rank}. "
    cap = normalize_short_caption(text, max_words=max_words)
    if not cap:
        return "Nice one"
    words = cap.split()
    while words and len(prefix) + len(" ".join(words)) > max_line_chars:
        words = words[:-1]
    out = " ".join(words) if words else cap[: max(0, max_line_chars - len(prefix))]
    return out if out else "Nice one"


def generate_shorts_overlay_commentary(
    settings: dict,
    clip: dict,
    *,
    topic_title: str,
    video_main_title: str,
    segment_rank: int,
    total_segments: int,
) -> str:
    """
    One short on-screen line from full Reddit + channel context (not stolen comments).
    """
    sc = settings.get("shorts") or {}
    ctx_cfg = settings.get("post_context", {})
    ch = settings.get("channel") or {}
    niche = str(ch.get("niche", "")).strip() or "general"
    channel_name = str(ch.get("name", "")).strip() or "channel"

    ctx = clip.get("commentary_context") or {}
    post_title = str(ctx.get("post_title") or clip.get("title", "")).strip()
    post_selftext = str(ctx.get("post_selftext") or "").strip()
    top_comments = ctx.get("top_comments") or []
    if not isinstance(top_comments, list):
        top_comments = []

    _cap = 5
    max_words = int(
        sc.get("overlay_comment_max_words", ctx_cfg.get("comment_max_words", _cap))
    )
    max_words = max(1, min(max_words, _cap))
    max_line_chars = overlay_line_max_chars(settings)
    preferred = sc.get("preferred_overlay_model") or None

    comments_block = (
        "\n".join(f"- {t}" for t in top_comments[:12])
        if top_comments
        else "(no comments collected)"
    )

    prompt = f"""You write ultra-short on-screen captions for a YouTube Shorts compilation.

Channel name: {channel_name}
Channel niche: {niche}
Compilation title (this video): {video_main_title}
Topic / theme for this Short: {topic_title}
This clip is item {segment_rank} of {total_segments} in the numbered list (1..{total_segments}).

--- Reddit post (this clip) ---
Title: {post_title}
Post body / description (OP text, may be empty):
{post_selftext or "(none)"}

Top comments (for context and tone; do not copy them verbatim):
{comments_block}

Metadata: r/{clip.get('subreddit', '')}, score {clip.get('score')}, ~{clip.get('duration_sec', 0)}s

Write exactly ONE caption for this clip. It will show as: "{segment_rank}. <your text>"

Rules:
- Short, engaging, witty or punchy when it fits {niche}.
- At most {max_words} words.
- No hashtags, no emojis.
- No quotation marks around the answer.
- Do not prefix with "{segment_rank}." — output ONLY the caption words after the number we add in editing.
- Output a single line of plain text, nothing else.
"""
    try:
        req = TextRequest(text=prompt)
        raw = text_service.generate(req, preferred_model=preferred).strip()
        raw = raw.strip('"').strip("'").strip()
        raw = re.sub(r"^[\d]+[\).\s]+", "", raw).strip()
        return _fit_caption_to_line(
            raw,
            rank=segment_rank,
            max_words=max_words,
            max_line_chars=max_line_chars,
        )
    except Exception as e:
        logger.warning("Shorts overlay commentary AI failed: %s", e)
        fb = normalize_short_caption(post_title, max_words=max_words) or "Wait for it"
        return _fit_caption_to_line(
            fb,
            rank=segment_rank,
            max_words=max_words,
            max_line_chars=max_line_chars,
        )


def generate_shorts_commentary(clip_title: str, topic: str) -> str:
    """
    Legacy: very short reaction (used when explicitly enabled elsewhere).
    """
    prompt = f"""Write a very short, funny/relevant reaction to this video.
Video Title: {clip_title}
Video Topic: {topic}

Rules:
- Length: 2 to 5 words EXACTLY.
- Tone: Casual/Funny.
- No hashtags, no emojis.
- Only the reaction text.

Example: "Wait for the end" or "Such a good boy" or "Pure chaos here".
"""
    try:
        req = TextRequest(text=prompt)
        result = text_service.generate(req).strip().strip('"').strip("'")

        normalized = normalize_short_caption(result, max_words=5)
        if normalized:
            return normalized
        return "Wait for it..."
    except Exception as e:
        logger.warning("Shorts commentary AI failed: %s", e)
        return "Wait for it..."
