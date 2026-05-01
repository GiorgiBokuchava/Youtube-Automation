"""Source portrait-friendly Reddit + Instagram clips for Shorts (search-driven)."""

from __future__ import annotations

import logging
import random
import re
import time
from pathlib import Path

from youtube_automation.ai.text.shorts_topic import ShortsTopicPlan, sanitize_shorts_topic_title
from youtube_automation.instagram.scraper import source_instagram_videos
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
from youtube_automation.sourcing import _interleave_weighted, instagram_sourcing_enabled
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
        selftext = selftext[:2500].rstrip() + "\u2026"

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


def _shorts_clip_allocation(
    n: int,
    r_w: float,
    i_w: float,
    *,
    reddit_ok: bool,
    instagram_ok: bool,
) -> tuple[int, int]:
    """Return (reddit_slots, instagram_slots) that sum to n when both sources are active."""
    if n <= 0:
        return 0, 0
    if not reddit_ok:
        return (0, n) if instagram_ok else (n, 0)
    if not instagram_ok:
        return n, 0
    total = r_w + i_w
    if total <= 0:
        return n, 0
    r_w /= total
    i_w /= total
    ig_n = int(round(n * i_w))
    ig_n = max(0, min(n, ig_n))
    r_n = n - ig_n
    if n >= 2:
        if ig_n == 0 and i_w > 0:
            ig_n = 1
            r_n = n - 1
        if r_n == 0 and r_w > 0:
            r_n = 1
            ig_n = n - 1
    return r_n, ig_n


def _build_shorts_main_title(topic_plan: ShortsTopicPlan, actual: int) -> str:
    title = sanitize_shorts_topic_title(topic_plan.topic_title)
    if "{count}" in title:
        return title.replace("{count}", str(actual))
    return title or f"Top {actual} Viral Moments"


def _normalize_instagram_short_clip(clip: dict, *, min_hw: float) -> dict | None:
    sz = probe_video_stream_size(Path(clip["local_path"]))
    if sz is None:
        logger.debug("Instagram shorts skip %s: probe failed", clip.get("id"))
        return None
    hw = _portrait_hw_score(sz.width, sz.height)
    if hw < min_hw:
        logger.debug(
            "Instagram shorts skip %s: not portrait enough (h/w=%.2f < %.2f)",
            clip.get("id"),
            hw,
            min_hw,
        )
        return None
    top_comments = clip.get("top_comments") or []
    if not isinstance(top_comments, list):
        top_comments = []
    return {
        **clip,
        "probe_w": sz.width,
        "probe_h": sz.height,
        "commentary_context": {
            "post_title": str(clip.get("title") or "").strip(),
            "post_selftext": str(clip.get("selftext") or "").strip(),
            "top_comments": [str(t) for t in top_comments[:12]],
        },
    }


def _source_shorts_instagram_clips(
    settings: dict,
    *,
    ig_target: int,
    min_hw: float,
    exclude_ids: set[str],
) -> list[dict]:
    if ig_target <= 0:
        return []
    fetch_cap = min(max(ig_target * 6, ig_target + 3), 36)
    cap_sec = fetch_cap * 60
    raw = source_instagram_videos(
        settings,
        duration_cap_seconds=cap_sec,
        warn_below_seconds=min(cap_sec, ig_target * 30),
        exclude_ids=exclude_ids,
        max_clips=fetch_cap,
    )
    accepted: list[dict] = []
    for c in raw:
        nc = _normalize_instagram_short_clip(c, min_hw=min_hw)
        if nc:
            accepted.append(nc)
        if len(accepted) >= ig_target:
            break
    return accepted[:ig_target]


def _source_shorts_reddit_clips(
    settings: dict,
    topic_plan: ShortsTopicPlan,
    reddit_target: int,
    used_ids: set[str],
) -> list[dict]:
    """Download up to ``reddit_target`` portrait Reddit video clips."""
    sc = settings.get("shorts") or {}
    post_cfg = settings.get("post", {})
    min_dur = int(sc.get("min_duration", post_cfg.get("min_duration", 2)))
    max_dur = int(sc.get("max_duration", min(post_cfg.get("max_duration", 60), 60)))

    min_score = int(sc.get("min_score", 10))
    min_ratio = float(sc.get("min_ratio", 0.10))
    min_hw = float(sc.get("min_height_width_ratio", 0.50))

    time_filter = str(sc.get("search_time_filter", "month"))
    sort = str(sc.get("search_sort", "top"))

    ctx = settings.get("post_context", {})
    comments_limit = int(ctx.get("top_comments", 5))
    _cmw = ctx.get("comment_max_words", 14)
    if _cmw in (None, False) or (isinstance(_cmw, int) and _cmw <= 0):
        context_max_words: int | None = None
    else:
        context_max_words = int(_cmw)

    queries = list(topic_plan.search_queries)

    ch = settings.get("channel") or {}
    niche_fallback = str(ch.get("niche", "animals")).lower()
    if niche_fallback not in queries:
        queries.append(niche_fallback)

    ffmpeg_location = ensure_ffmpeg()
    reddit = create_reddit_client()
    used = set(used_ids) | set(get_used_video_ids(settings))

    subs = list(settings.get("subreddits", []))
    random.shuffle(subs)
    active_subs_str = "+".join(subs[: min(50, len(subs))])

    seen: set[str] = set()
    candidates: list = []

    def _do_search(sq: str):
        try:
            logger.info("Searching r/%s for query: %r", active_subs_str, sq)
            subreddit = reddit.subreddit(active_subs_str)
            found = list(
                search_subreddit(
                    subreddit,
                    sq,
                    sort=sort,
                    time_filter=time_filter,
                    limit=500,
                )
            )
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

    for query in queries:
        if len(candidates) >= reddit_target * 2:
            break
        _do_search(query)

    candidates.sort(key=lambda s: int(s.score), reverse=True)

    accepted: list[dict] = []
    for submission in candidates:
        if len(accepted) >= reddit_target:
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

    if len(accepted) < reddit_target:
        logger.warning(
            "Shorts Reddit: only found %d/%d clips after search",
            len(accepted),
            reddit_target,
        )

    return accepted


def source_shorts_clips(settings: dict, topic_plan: ShortsTopicPlan) -> tuple[list[dict], str]:
    """
    Download up to topic_plan.clip_count clips from Reddit and Instagram.

    Strategy ``multi_source_strategy`` (shorts YAML):
    - ``reddit_first`` (default): fill from Reddit, then Instagram for the remainder.
    - ``instagram_first``: the opposite.
    - ``interleave``: use ``source_split`` weights and interleave clips (legacy).
    """
    target_n = int(topic_plan.clip_count)
    sc = settings.get("shorts") or {}
    min_hw = float(sc.get("min_height_width_ratio", 0.50))

    split_cfg = settings.get("source_split") or {}
    r_w = float(split_cfg.get("reddit", 1.0))
    i_w = float(split_cfg.get("instagram", 0.0))
    ig_ok = instagram_sourcing_enabled(settings)
    subs = list(settings.get("subreddits") or [])
    reddit_ok = bool(subs)
    if not ig_ok:
        i_w = 0.0
    if not reddit_ok:
        r_w = 0.0

    total_w = r_w + i_w
    if total_w <= 0:
        r_w, i_w = 1.0, 0.0
        ig_ok = False
    else:
        r_w /= total_w
        i_w /= total_w

    used_base = set(get_used_video_ids(settings))
    merged: list[dict] = []

    strategy = str(sc.get("multi_source_strategy", "reddit_first")).strip().lower()

    def exclude_ids() -> set[str]:
        return used_base | {c["id"] for c in merged}

    def pull_reddit(need: int) -> list[dict]:
        if not reddit_ok or need <= 0:
            return []
        return _source_shorts_reddit_clips(settings, topic_plan, need, exclude_ids())

    def pull_ig(need: int) -> list[dict]:
        if not ig_ok or need <= 0:
            return []
        try:
            return _source_shorts_instagram_clips(
                settings,
                ig_target=need,
                min_hw=min_hw,
                exclude_ids=exclude_ids(),
            )
        except Exception as e:
            logger.warning(
                "Instagram shorts sourcing failed (%s); other sources continue.",
                e,
            )
            return []

    if strategy == "interleave":
        r_alloc, ig_alloc = _shorts_clip_allocation(
            target_n,
            r_w,
            i_w,
            reddit_ok=reddit_ok,
            instagram_ok=ig_ok,
        )
        logger.info(
            "Shorts sourcing plan (interleave): target=%d reddit_slots=%d instagram_slots=%d "
            "(weights r=%.2f i=%.2f)",
            target_n,
            r_alloc,
            ig_alloc,
            r_w,
            i_w,
        )
        reddit_part = pull_reddit(r_alloc) if r_alloc > 0 else []
        ig_part = pull_ig(ig_alloc) if ig_alloc > 0 else []
        merged = _interleave_weighted(reddit_part, ig_part, r_w, i_w)
    elif strategy == "instagram_first":
        logger.info("Shorts sourcing plan (instagram_first): target=%d", target_n)
        merged.extend(pull_ig(target_n))
        merged.extend(pull_reddit(target_n - len(merged)))
    else:
        if strategy != "reddit_first":
            logger.warning("Unknown shorts multi_source_strategy %r; using reddit_first", strategy)
        logger.info("Shorts sourcing plan (reddit_first): target=%d", target_n)
        merged.extend(pull_reddit(target_n))
        merged.extend(pull_ig(target_n - len(merged)))

    need = target_n - len(merged)
    guard = 0
    while need > 0 and guard < 24:
        guard += 1
        progressed = False
        if reddit_ok:
            more_r = pull_reddit(need)
            if more_r:
                merged.extend(more_r)
                progressed = True
        need = target_n - len(merged)
        if need <= 0:
            break
        more_i = pull_ig(need)
        if more_i:
            merged.extend(more_i)
            progressed = True

        need = target_n - len(merged)
        if not progressed:
            break

    merged.sort(key=lambda c: int(c.get("score", 0)), reverse=True)
    merged = merged[:target_n]

    if len(merged) < target_n:
        logger.warning(
            "Shorts: only sourced %d/%d clips after Reddit + Instagram — filters may be tight",
            len(merged),
            target_n,
        )

    actual = len(merged)
    main_title = _build_shorts_main_title(topic_plan, actual)
    return merged, main_title
