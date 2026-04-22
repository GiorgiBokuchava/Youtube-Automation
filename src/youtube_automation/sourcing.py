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


def _interleave_weighted(
    reddit_clips: list[dict],
    instagram_clips: list[dict],
    reddit_weight: float,
    instagram_weight: float,
) -> list[dict]:
    """Interleave two clip lists to roughly match weighted distribution by count."""
    if not reddit_clips:
        return list(instagram_clips)
    if not instagram_clips:
        return list(reddit_clips)

    # If both weights are zero/invalid, fall back to alternating.
    total = reddit_weight + instagram_weight
    if total <= 0:
        reddit_weight, instagram_weight = 0.5, 0.5
    else:
        reddit_weight /= total
        instagram_weight /= total

    merged: list[dict] = []
    r_idx = i_idx = 0
    picked_r = picked_i = 0

    while r_idx < len(reddit_clips) or i_idx < len(instagram_clips):
        if r_idx >= len(reddit_clips):
            merged.extend(instagram_clips[i_idx:])
            break
        if i_idx >= len(instagram_clips):
            merged.extend(reddit_clips[r_idx:])
            break

        # Choose the source that is furthest behind its expected share.
        step = picked_r + picked_i + 1
        r_gap = (step * reddit_weight) - picked_r
        i_gap = (step * instagram_weight) - picked_i

        if r_gap >= i_gap:
            merged.append(reddit_clips[r_idx])
            r_idx += 1
            picked_r += 1
        else:
            merged.append(instagram_clips[i_idx])
            i_idx += 1
            picked_i += 1

    return merged


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

    reddit_budget = _split_budget(effective_target, r_w) if r_w > 0 else 0
    ig_budget = _split_budget(effective_target, i_w) if i_w > 0 else 0

    reddit_warn = int(final_target_seconds * r_w) if r_w > 0 else final_target_seconds
    ig_warn = int(final_target_seconds * i_w) if i_w > 0 else final_target_seconds

    clips_r: list[dict] = []
    clips_i: list[dict] = []
    used_ids_in_run: set[str] = set()

    def _append_unique(dst: list[dict], incoming: list[dict]) -> int:
        added = 0
        for clip in incoming:
            cid = clip.get("id")
            if not cid or cid in used_ids_in_run:
                continue
            used_ids_in_run.add(cid)
            dst.append(clip)
            added += 1
        return added

    if r_w > 0 and reddit_budget > 0:
        batch = source_videos(
            settings,
            duration_cap_seconds=reddit_budget,
            warn_below_seconds=reddit_warn,
            exclude_ids=used_ids_in_run,
        )
        added = _append_unique(clips_r, batch)
        logger.info("Reddit contributed %d clip(s) in initial pass.", added)

    if i_w > 0 and ig_budget > 0 and instagram_sourcing_enabled(settings):
        batch = source_instagram_videos(
            settings,
            duration_cap_seconds=ig_budget,
            warn_below_seconds=ig_warn,
            exclude_ids=used_ids_in_run,
        )
        added = _append_unique(clips_i, batch)
        logger.info("Instagram contributed %d clip(s) in initial pass.", added)

    def _duration(clips: list[dict]) -> int:
        return sum(int(c.get("duration_sec") or 0) for c in clips)

    total_duration = _duration(clips_r) + _duration(clips_i)
    remaining = max(0, effective_target - total_duration)
    can_reddit = bool(r_w > 0 and subs)
    can_ig = bool(i_w > 0 and instagram_sourcing_enabled(settings))

    # Top-up pass: if one source cannot satisfy its split, fill the remaining
    # target duration by trying the other available source(s).
    while remaining > 0 and (can_reddit or can_ig):
        progress = False
        prefer_reddit = _duration(clips_r) <= _duration(clips_i)

        ordered_sources: list[str] = (
            ["reddit", "instagram"] if prefer_reddit else ["instagram", "reddit"]
        )
        for source_name in ordered_sources:
            if source_name == "reddit":
                if not can_reddit:
                    continue
                batch = source_videos(
                    settings,
                    duration_cap_seconds=remaining,
                    warn_below_seconds=remaining,
                    exclude_ids=used_ids_in_run,
                )
                added = _append_unique(clips_r, batch)
                if added == 0:
                    can_reddit = False
                    continue
                progress = True
                logger.info(
                    "Top-up pass: Reddit added %d clip(s), remaining=%ds.",
                    added,
                    max(0, effective_target - (_duration(clips_r) + _duration(clips_i))),
                )
            else:
                if not can_ig:
                    continue
                batch = source_instagram_videos(
                    settings,
                    duration_cap_seconds=remaining,
                    warn_below_seconds=remaining,
                    exclude_ids=used_ids_in_run,
                )
                added = _append_unique(clips_i, batch)
                if added == 0:
                    can_ig = False
                    continue
                progress = True
                logger.info(
                    "Top-up pass: Instagram added %d clip(s), remaining=%ds.",
                    added,
                    max(0, effective_target - (_duration(clips_r) + _duration(clips_i))),
                )

            remaining = max(0, effective_target - (_duration(clips_r) + _duration(clips_i)))
            if remaining <= 0:
                break

        if not progress:
            break

    seen_ids: set[str] = set()
    unique_r: list[dict] = []
    unique_i: list[dict] = []
    for c in clips_r:
        cid = c.get("id")
        if not cid or cid in seen_ids:
            continue
        seen_ids.add(cid)
        unique_r.append(c)
    for c in clips_i:
        cid = c.get("id")
        if not cid or cid in seen_ids:
            continue
        seen_ids.add(cid)
        unique_i.append(c)

    merged = _interleave_weighted(unique_r, unique_i, r_w, i_w)

    logger.info(
        "Combined sourcing: %d clip(s), ~%ds total sourced duration (target %d min).",
        len(merged),
        sum(int(c.get("duration_sec") or 0) for c in merged),
        final_target_minutes,
    )
    return merged
