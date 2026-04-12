"""Source portrait-friendly Reddit video clips for Shorts (search-driven)."""

from __future__ import annotations

import logging
import random
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
from youtube_automation.utils.text_sanitize import truncate_preserve_unicode

logger = logging.getLogger(__name__)


def _overlay_caption_from_submission(
    submission,
    *,
    context_limit: int,
    comment_max_len: int,
    context_max_words: int | None,
) -> str:
    """Prefer a short top comment; else title. Keeps emojis (only banned-word filter)."""
    try:
        submission.comment_sort = "top"
        submission.comments.replace_more(limit=0)
        for c in submission.comments.list():
            if context_limit <= 0:
                break
            body = getattr(c, "body", "").strip()
            if not body or body in ("[deleted]", "[removed]"):
                continue
            if context_max_words is not None and _word_count(body) > context_max_words:
                continue
            if not _comment_is_clean(body):
                continue
            return truncate_preserve_unicode(body, comment_max_len)
    except Exception:
        pass
    title = (submission.title or "").strip()
    return truncate_preserve_unicode(title, comment_max_len)


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
    min_score = int(sc.get("min_score", post_cfg.get("min_score", 50)))
    min_ratio = float(sc.get("min_ratio", post_cfg.get("min_ratio", 0.75)))
    min_hw = float(sc.get("min_height_width_ratio", 0.82))  # tall / portrait-ish
    search_limit = int(sc.get("search_limit_per_subreddit", 35))
    time_filter = str(sc.get("search_time_filter", "month"))
    sort = str(sc.get("search_sort", "top"))

    ctx = settings.get("post_context", {})
    comments_limit = int(ctx.get("top_comments", 5))
    comment_max_len = int(sc.get("overlay_comment_max_len", ctx.get("comment_max_len", 120)))
    _cmw = ctx.get("comment_max_words", 14)
    if _cmw in (None, False) or (isinstance(_cmw, int) and _cmw <= 0):
        context_max_words: int | None = None
    else:
        context_max_words = int(_cmw)

    target_n = int(topic_plan.clip_count)
    query = topic_plan.search_query.strip()

    ffmpeg_location = ensure_ffmpeg()
    reddit = create_reddit_client()
    used = get_used_video_ids(settings)
    subs = list(settings.get("subreddits", []))
    random.shuffle(subs)

    # Gather candidate submissions (unique by id)
    seen: set[str] = set()
    candidates: list = []
    for sub in subs:
        try:
            subreddit = reddit.subreddit(sub)
            found = search_subreddit(
                subreddit,
                query,
                sort=sort,
                time_filter=time_filter,
                limit=search_limit,
            )
        except Exception as e:
            logger.debug("Search failed for r/%s: %s", sub, e)
            continue
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

        caption = _overlay_caption_from_submission(
            submission,
            context_limit=comments_limit,
            comment_max_len=comment_max_len,
            context_max_words=context_max_words,
        )
        if not caption:
            caption = truncate_preserve_unicode(submission.title or "", comment_max_len)

        accepted.append(
            {
                "id": sid,
                "title": submission.title or "",
                "overlay_caption": caption,
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
            }
        )
        time.sleep(random.uniform(0.2, 0.55))

    if len(accepted) < target_n:
        logger.warning(
            "Shorts: only found %d/%d clips for query %r — relax shorts.* filters or subreddits",
            len(accepted),
            target_n,
            query,
        )

    # Rank 1 = highest score → display order countdown: worst … best
    accepted.sort(key=lambda c: int(c.get("score", 0)))  # ascending: low first
    actual = len(accepted)
    main_title = f"Top {actual} {topic_plan.topic_title} moments"
    return accepted, main_title
