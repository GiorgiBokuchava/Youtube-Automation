"""Source portrait-friendly Reddit video clips for Shorts (search-driven)."""

from __future__ import annotations

import logging
import random
import re
import time
from pathlib import Path
from youtube_automation.ai.text.shorts_topic import ShortsTopicPlan
from youtube_automation.media.ffmpeg import ensure_ffmpeg
from youtube_automation.media.ffprobe_streams import probe_video_stream_size
from youtube_automation.media.video import (
    _comment_is_clean,
    _compute_timeout_seconds,
    _download_reddit_video,
    _get_reddit_video_duration,
    _word_count,
)
from youtube_automation.reddit.client import create_reddit_client, search_subreddit
from youtube_automation.storage.sessions import get_used_video_ids

logger = logging.getLogger(__name__)


def overlay_line_max_chars(settings: dict) -> int:
    """Approximate max characters for one overlay list line (prefix + text) at 1080-wide Shorts."""
    sc = settings.get("shorts") or {}
    if sc.get("overlay_comment_max_chars") is not None:
        return max(16, int(sc["overlay_comment_max_chars"]))
    body_font = float(sc.get("overlay_body_font_size", 28))
    margin_x = float(sc.get("overlay_list_margin_x", 56))
    margin_right = float(sc.get("overlay_margin_right", 40))
    video_w = float(sc.get("overlay_video_width", 1080))
    inner = max(0.0, video_w - margin_x - margin_right)
    return max(24, int(inner / (body_font * 0.52)))


def _strip_overlay_markdown(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _collect_commentary_context_for_ai(
    submission,
    *,
    comments_limit: int,
    context_max_words: int | None,
    max_comment_chars: int = 600,
) -> dict[str, object]:
    """Gather post title, body, and top comments for AI overlay generation (not for direct display)."""
    comments_text: list[str] = []
    try:
        submission.comment_sort = "top"
        submission.comments.replace_more(limit=0)
        seen = 0
        for c in submission.comments.list():
            if comments_limit > 0 and seen >= comments_limit:
                break
            body = getattr(c, "body", "").strip()
            if not body or body in ("[deleted]", "[removed]"):
                continue
            if context_max_words is not None and _word_count(body) > context_max_words:
                continue
            if not _comment_is_clean(body):
                continue
            seen += 1
            cleaned = _strip_overlay_markdown(body)
            if cleaned:
                comments_text.append(cleaned[:max_comment_chars])
    except Exception:
        pass

    raw_self = (submission.selftext or "").strip()
    selftext = _strip_overlay_markdown(raw_self)
    if len(selftext) > 2500:
        selftext = selftext[:2500].rstrip() + "…"

    return {
        "post_title": submission.title or "",
        "post_selftext": selftext,
        "top_comments": comments_text,
    }


def _portrait_hw_score(width: int, height: int) -> float:
    """Higher when the frame is taller (closer to 9:16 portrait)."""
    if width <= 0 or height <= 0:
        return 0.0
    return float(height) / float(width)


def source_shorts_clips(settings: dict, topic_plan: ShortsTopicPlan) -> tuple[list[dict], str]:
    """
    Download up to topic_plan.clip_count clips matching the search query.
    Returns (clips ordered worst→best for countdown display, main_title_for_video).
    """
    sc = settings.get("shorts") or {}
    post_cfg = settings.get("post", {})
    min_dur = int(sc.get("min_duration", post_cfg.get("min_duration", 2)))
    max_dur = int(sc.get("max_duration", min(post_cfg.get("max_duration", 60), 60)))
    
    # RELAXED FILTERS for high yield
    min_score = int(sc.get("min_score", 10))
    min_ratio = float(sc.get("min_ratio", 0.10))
    min_hw = float(sc.get("min_height_width_ratio", 0.50))
    search_limit = int(sc.get("search_limit_per_subreddit", 100))
    
    time_filter = str(sc.get("search_time_filter", "month"))
    sort = str(sc.get("search_sort", "top"))

    ctx = settings.get("post_context", {})
    comments_limit = int(ctx.get("top_comments", 5))
    _cmw = ctx.get("comment_max_words", 14)
    if _cmw in (None, False) or (isinstance(_cmw, int) and _cmw <= 0):
        context_max_words: int | None = None
    else:
        context_max_words = int(_cmw)

    target_n = int(topic_plan.clip_count)
    queries = list(topic_plan.search_queries)
    
    # Add a super-broad fallback query based on the niche if needed
    ch = settings.get("channel") or {}
    niche_fallback = str(ch.get("niche", "animals")).lower()
    if niche_fallback not in queries:
        queries.append(niche_fallback)

    ffmpeg_location = ensure_ffmpeg()
    reddit = create_reddit_client()
    used = get_used_video_ids(settings)
    
    # Use a multi-reddit search to combine subreddits efficiently
    subs = list(settings.get("subreddits", []))
    random.shuffle(subs)
    # Reddit search allows up to ~40-50 subreddits in one query string
    active_subs_str = "+".join(subs[:min(50, len(subs))])

    # Gather candidate submissions (unique by id)
    seen: set[str] = set()
    candidates: list = []
    
    def _do_search(sq: str):
        try:
            logger.info("Searching r/%s for query: %r", active_subs_str, sq)
            subreddit = reddit.subreddit(active_subs_str)
            found = list(search_subreddit(
                subreddit,
                sq,
                sort=sort,
                time_filter=time_filter,
                limit=500, # Maximize search reach
            ))
            for s in found:
                sid = s.id
                if sid in seen or sid in used:
                    continue
                seen.add(sid)
                if not getattr(s, "is_video", False):
                    continue
                if float(s.upvote_ratio or 0.0) < min_ratio:
                    continue
                dur = _get_reddit_video_duration(s)
                if dur is None or not (min_dur <= dur <= max_dur):
                    continue
                if int(s.score) < min_score:
                    continue
                candidates.append(s)
        except Exception as e:
            logger.warning("Multi-reddit search failed: %s", e)

    # Loop through queries until we have enough candidates
    for query in queries:
        if len(candidates) >= target_n * 2:
            break
        _do_search(query)

    # Prefer higher Reddit score first, then try to keep portrait after probe
    candidates.sort(key=lambda s: int(s.score), reverse=True)

    accepted: list[dict] = []
    for submission in candidates:
        if len(accepted) >= target_n:
            break
        sid = submission.id
        timeout = _compute_timeout_seconds(int(_get_reddit_video_duration(submission) or 30))
        try:
            path = _download_reddit_video(submission, ffmpeg_location, timeout)
        except Exception as e:
            logger.debug("Download failed %s: %s", sid, e)
            continue

        sz = probe_video_stream_size(Path(path))
        if sz is None:
            logger.debug("Probe failed for %s", sid)
            continue
        hw = _portrait_hw_score(sz.width, sz.height)
        if hw < min_hw:
            logger.debug(
                "Skip %s: not portrait enough (h/w=%.2f < %.2f)",
                sid,
                hw,
                min_hw,
            )
            continue

        accepted.append(
            {
                "id": sid,
                "title": submission.title or "",
                "permalink": f"https://www.reddit.com{submission.permalink}",
                "source_url": submission.url,
                "subreddit": submission.subreddit.display_name,
                "author": (
                    getattr(submission.author, "name", "unknown")
                    if submission.author
                    else "unknown"
                ),
                "duration_sec": int(_get_reddit_video_duration(submission) or 0),
                "local_path": path,
                "score": int(submission.score),
                "upvote_ratio": float(submission.upvote_ratio or 0.0),
                "probe_w": sz.width,
                "probe_h": sz.height,
                "commentary_context": _collect_commentary_context_for_ai(
                    submission,
                    comments_limit=comments_limit,
                    context_max_words=context_max_words,
                ),
            }
        )
        time.sleep(random.uniform(0.1, 0.35))

    if len(accepted) < target_n:
        logger.warning(
            "Shorts: only found %d/%d clips after full search — yield might be low",
            len(accepted),
            target_n,
        )

    # Rank 1 = highest score → display order countdown: worst … best
    accepted.sort(key=lambda c: int(c.get("score", 0)), reverse=True)
    actual = len(accepted)
    if "{count}" in topic_plan.topic_title:
        main_title = topic_plan.topic_title.replace("{count}", str(actual))
    else:
        main_title = topic_plan.topic_title or f"Top {actual} Viral Moments"
    return accepted, main_title
