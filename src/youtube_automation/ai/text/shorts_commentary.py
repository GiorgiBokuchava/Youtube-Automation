from __future__ import annotations

import logging
import re

from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest
from youtube_automation.media.shorts_sourcing import overlay_line_max_chars

logger = logging.getLogger(__name__)


def _strip_ai_rank_echo(text: str, segment_rank: int) -> str:
    """Remove only a leading enumeration echo that matches this clip's display slot."""
    t = (text or "").strip().strip('"').strip("'")
    if not t:
        return t
    # Slot-specific only - avoids eating legitimate captions like "2 dogs ..."
    n = int(segment_rank)
    for pattern in (
        rf"^\s*{n}\s*\.\s+",
        rf"^\s*{n}\s*\)\s+",
        rf"^\s*{n}\s*[\-\u2013]\s+",
        rf"(?i)^\s*(?:clip|part)\s*{n}\s*[\.:\-\u2013]\s*",
    ):
        t2 = re.sub(pattern, "", t, count=1).strip()
        if t2 != t:
            return t2
    return t


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

Numbering on-screen (important): clips are labeled in playback order as 1., 2., 3., ...
This clip will appear as number **{segment_rank}** in that list when it is shown.
Up to **{total_segments}** clips are sourced for this Short - some may be dropped during editing,
so do NOT say "part X of Y" or rely on totals; focus only on this clip.

--- Source post for this clip (Reddit or Instagram) ---
Title: {post_title}
Post body / description (OP text, may be empty):
{post_selftext or "(none)"}

Top comments (for context and tone; do not copy them verbatim):
{comments_block}

Metadata: source={clip.get("subreddit", "")}, score/likes {clip.get("score")}, ~{clip.get("duration_sec", 0)}s

Write exactly ONE caption for this clip. In the final video it is shown as line **{segment_rank}.** followed by your text.

Rules:
- Short, engaging, witty or punchy when it fits {niche}.
- At most {max_words} words.
- No hashtags, no emojis.
- No quotation marks around the answer.
- Output ONLY the caption words (no leading number, no "1.", no "Clip 3:" - we add the number in editing).
- Do not start your caption with the digit **{segment_rank}** followed by punctuation - it duplicates the label.
- Output a single line of plain text, nothing else.
"""
    try:
        req = TextRequest(text=prompt)
        raw = text_service.generate(req, preferred_model=preferred).strip()
        raw = _strip_ai_rank_echo(raw, segment_rank)
        return _fit_caption_to_line(
            raw,
            rank=segment_rank,
            max_words=max_words,
            max_line_chars=max_line_chars,
        )
    except Exception as e:
        logger.warning("Shorts overlay commentary AI failed: %s", e)
        fb = normalize_short_caption(post_title, max_words=max_words) or "Wait for it"
        fb = _strip_ai_rank_echo(fb, segment_rank)
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
