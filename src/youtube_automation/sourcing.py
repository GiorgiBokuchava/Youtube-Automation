from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)


def instagram_sourcing_enabled(settings: dict) -> bool:
    """True when YAML requests Instagram and hashtags are configured."""
    split = float((settings.get("source_split") or {}).get("instagram", 0.0))
    if split <= 0:
        return False
    ig = settings.get("instagram") or {}
    hashtags = [h for h in (ig.get("hashtags") or []) if str(h).strip()]
    return bool(hashtags)


def _split_budget(
    effective_target: int,
    weight: float,
) -> int:
    if weight <= 0:
        return 0
    b = int(effective_target * weight)
    if b == 0 and effective_target > 0:
        return 1
    return b


def source_all_videos(settings: dict) -> List[dict]:
    """
    Merge Reddit and Instagram clips according to ``source_split`` and shared
    duration/over-source settings.
    """
    from youtube_automation.instagram.scraper import source_instagram_videos
    from youtube_automation.media.video import source_videos

    final_target_minutes = settings.get("final_target_duration", 10)
    final_target_seconds = int(final_target_minutes * 60)

    post_cfg = settings.get("post", {})
    over_source_pct = int(post_cfg.get("over_source_pct", 25))
    effective_target = int(final_target_seconds * (1 + over_source_pct / 100))

    split_cfg = settings.get("source_split") or {}
    r_w = float(split_cfg.get("reddit", 1.0))
    i_w = float(split_cfg.get("instagram", 0.0))
    if not instagram_sourcing_enabled(settings):
        i_w = 0.0
    subs = settings.get("subreddits") or []
    if not subs:
        r_w = 0.0

    total_w = r_w + i_w
    if total_w <= 0:
        r_w, i_w = 1.0, 0.0
    else:
        r_w /= total_w
        i_w /= total_w

    reddit_budget = _split_budget(effective_target, r_w)
    ig_budget = _split_budget(effective_target, i_w)

    reddit_warn = int(final_target_seconds * r_w) if r_w > 0 else final_target_seconds
    ig_warn = int(final_target_seconds * i_w) if i_w > 0 else final_target_seconds

    merged: list[dict] = []
    seen_ids: set[str] = set()

    if r_w > 0 and reddit_budget > 0:
        clips_r = source_videos(
            settings,
            duration_cap_seconds=reddit_budget,
            warn_below_seconds=reddit_warn,
        )
        for c in clips_r:
            cid = c.get("id")
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                merged.append(c)
        logger.info("Reddit contributed %d clip(s).", len(clips_r))

    if i_w > 0 and ig_budget > 0 and instagram_sourcing_enabled(settings):
        clips_i = source_instagram_videos(
            settings,
            duration_cap_seconds=ig_budget,
            warn_below_seconds=ig_warn,
        )
        for c in clips_i:
            cid = c.get("id")
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                merged.append(c)
        logger.info("Instagram contributed %d clip(s).", len(clips_i))

    logger.info(
        "Combined sourcing: %d clip(s), ~%ds total sourced duration (target %d min).",
        len(merged),
        sum(int(c.get("duration_sec") or 0) for c in merged),
        final_target_minutes,
    )
    return merged
