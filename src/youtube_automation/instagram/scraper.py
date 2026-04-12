from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Generator

import instaloader

from youtube_automation.instagram.client import (
    SESSION_USERNAME_DEFAULT,
    build_loader,
    session_file_path,
)
from youtube_automation.storage.sessions import get_used_video_ids
from youtube_automation.utils.paths import DOWNLOADS

logger = logging.getLogger(__name__)

MEDIA_TYPE_VIDEO = 2


def _caption_text(media: dict) -> str:
    cap = media.get("caption")
    if cap is None:
        return ""
    if isinstance(cap, dict):
        return (cap.get("text") or "").strip()
    return str(cap).strip()


def iter_hashtag_section(
    L: instaloader.Instaloader,
    keyword: str,
    section_key: str,
    limit: int,
) -> Generator[dict, None, None]:
    """Raw media dicts from hashtag top/recent via ``api/v1/tags/web_info/``."""
    params: dict = {"__a": 1, "__d": "dis", "tag_name": keyword}
    seen = 0
    page_num = 0

    while True:
        page_num += 1
        try:
            resp = L.context.get_iphone_json("api/v1/tags/web_info/", params)
        except instaloader.exceptions.TooManyRequestsException:
            logger.warning(
                "Instagram rate limited for #%s [%s] page=%d — waiting 60s...",
                keyword,
                section_key,
                page_num,
            )
            time.sleep(60)
            continue
        except Exception as exc:
            logger.warning(
                "Instagram hashtag API error for #%s [%s] page=%d: %s",
                keyword,
                section_key,
                page_num,
                exc,
            )
            break

        if not isinstance(resp, dict):
            logger.warning(
                "Instagram unexpected response type for #%s [%s] page=%d: %r",
                keyword,
                section_key,
                page_num,
                type(resp).__name__,
            )
            break

        data = resp.get("data", {})
        if page_num == 1:
            logger.info(
                "Instagram response keys for #%s [%s]: top-level=%s data_keys=%s",
                keyword,
                section_key,
                sorted(resp.keys()),
                sorted(data.keys()) if isinstance(data, dict) else [],
            )

        section_data = data.get(section_key, {})
        if not section_data:
            logger.warning(
                "Instagram missing section data for #%s [%s] page=%d. data_keys=%s",
                keyword,
                section_key,
                page_num,
                sorted(data.keys()) if isinstance(data, dict) else [],
            )
            break

        sections = section_data.get("sections", [])
        logger.info(
            "Instagram page #%d for #%s [%s]: sections=%d more_available=%s next_max_id=%s",
            page_num,
            keyword,
            section_key,
            len(sections),
            bool(section_data.get("more_available")),
            bool(section_data.get("next_max_id")),
        )

        page_video_count = 0

        for section in sections:
            medias = section.get("layout_content", {}).get("medias", [])
            for item in medias:
                media = item.get("media", {})
                if media.get("media_type") != MEDIA_TYPE_VIDEO:
                    continue
                page_video_count += 1
                seen += 1
                yield media
                if seen >= limit:
                    logger.info(
                        "Instagram limit reached for #%s [%s]: yielded=%d",
                        keyword,
                        section_key,
                        seen,
                    )
                    return

        logger.info(
            "Instagram page #%d yielded %d video candidates for #%s [%s]",
            page_num,
            page_video_count,
            keyword,
            section_key,
        )

        if not section_data.get("more_available"):
            break

        next_max_id = section_data.get("next_max_id")
        if not next_max_id:
            break

        params = {"__a": 1, "__d": "dis", "tag_name": keyword, "max_id": next_max_id}


def _pick_downloaded_mp4(shortcode: str) -> Path | None:
    folder = DOWNLOADS / shortcode
    if not folder.is_dir():
        return None
    mp4s = list(folder.glob("*.mp4"))
    if not mp4s:
        return None
    return max(mp4s, key=lambda p: p.stat().st_size)


def _download_instagram_video(
    L: instaloader.Instaloader,
    media: dict,
    shortcode: str,
    delay: float,
) -> Path | None:
    try:
        post = instaloader.Post.from_iphone_struct(L.context, media)
        L.download_post(post, target=shortcode)
        path = _pick_downloaded_mp4(shortcode)
        if path:
            time.sleep(delay)
        return path
    except Exception as exc:
        logger.debug("Instagram download failed for %s: %s", shortcode, exc)
        return None


def source_instagram_videos(
    settings: dict,
    *,
    duration_cap_seconds: int,
    warn_below_seconds: int,
) -> list[dict]:
    """
    Download Instagram reel/video posts matching channel ``instagram`` settings.

    ``duration_cap_seconds`` caps total *accepted* clip duration.
    """
    ig = settings.get("instagram") or {}
    hashtags = [
        str(h).lstrip("#").strip() for h in (ig.get("hashtags") or []) if str(h).strip()
    ]
    if not hashtags:
        logger.warning("Instagram sourcing disabled: no hashtags configured.")
        return []

    min_likes = int(ig.get("min_likes", 5000))
    min_dur = float(ig.get("min_duration", 3))
    max_dur = float(ig.get("max_duration", 60))
    section_mode = str(ig.get("section", "both"))
    limit = int(ig.get("limit_per_hashtag", 100))
    delay = float(ig.get("delay", 2.0))
    session_username = str(ig.get("session_username", SESSION_USERNAME_DEFAULT))

    previously_used = get_used_video_ids(settings)
    seen_ids: set[str] = set()
    accepted: list[dict] = []
    total_duration = 0

    random.shuffle(hashtags)

    logger.info(
        "Instagram sourcing: cap=%ds, warn_below=%ds, hashtags=%d, "
        "likes>=%d duration=%.1f-%.1fs section=%s limit=%d previously_used=%d",
        duration_cap_seconds,
        warn_below_seconds,
        len(hashtags),
        min_likes,
        min_dur,
        max_dur,
        section_mode,
        limit,
        len(previously_used),
    )
    logger.info("Instagram hashtags after shuffle: %s", ", ".join(hashtags))

    L = build_loader(
        session_file_path(),
        download_dir=DOWNLOADS,
        session_username=session_username,
    )

    sections_to_scan: list[tuple[str, str]] = []
    if section_mode in ("top", "both"):
        sections_to_scan.append(("top", "top"))
    if section_mode in ("recent", "both"):
        sections_to_scan.append(("recent", "recent"))

    total_stats = {
        "raw_media_seen": 0,
        "missing_shortcode": 0,
        "duplicate_in_run": 0,
        "already_used": 0,
        "low_likes": 0,
        "bad_duration": 0,
        "download_failed": 0,
        "accepted": 0,
    }

    for tag in hashtags:
        if total_duration >= duration_cap_seconds:
            break

        tag_stats = {
            "raw_media_seen": 0,
            "missing_shortcode": 0,
            "duplicate_in_run": 0,
            "already_used": 0,
            "low_likes": 0,
            "bad_duration": 0,
            "download_failed": 0,
            "accepted": 0,
        }

        logger.info("Instagram tag start: #%s", tag)

        for section_key, label in sections_to_scan:
            if total_duration >= duration_cap_seconds:
                break

            logger.info("Instagram tag #%s scanning section=%s", tag, label)

            for media in iter_hashtag_section(L, tag, section_key, limit):
                if total_duration >= duration_cap_seconds:
                    break

                total_stats["raw_media_seen"] += 1
                tag_stats["raw_media_seen"] += 1

                shortcode = media.get("code") or ""
                like_count = int(media.get("like_count") or 0)
                duration = float(media.get("video_duration") or 0.0)

                if not shortcode:
                    total_stats["missing_shortcode"] += 1
                    tag_stats["missing_shortcode"] += 1
                    logger.debug(
                        "Instagram skip #%s [%s]: missing shortcode | likes=%s duration=%s",
                        tag,
                        label,
                        like_count,
                        duration,
                    )
                    continue

                if shortcode in seen_ids:
                    total_stats["duplicate_in_run"] += 1
                    tag_stats["duplicate_in_run"] += 1
                    logger.debug(
                        "Instagram skip #%s [%s]: duplicate in this run %s",
                        tag,
                        label,
                        shortcode,
                    )
                    continue

                if shortcode in previously_used:
                    total_stats["already_used"] += 1
                    tag_stats["already_used"] += 1
                    logger.debug(
                        "Instagram skip #%s [%s]: already used %s",
                        tag,
                        label,
                        shortcode,
                    )
                    continue

                if like_count < min_likes:
                    total_stats["low_likes"] += 1
                    tag_stats["low_likes"] += 1
                    logger.debug(
                        "Instagram skip #%s [%s]: low likes %s likes=%d < %d",
                        tag,
                        label,
                        shortcode,
                        like_count,
                        min_likes,
                    )
                    continue

                if not (min_dur <= duration <= max_dur):
                    total_stats["bad_duration"] += 1
                    tag_stats["bad_duration"] += 1
                    logger.debug(
                        "Instagram skip #%s [%s]: bad duration %s duration=%.2fs not in %.2f-%.2fs",
                        tag,
                        label,
                        shortcode,
                        duration,
                        min_dur,
                        max_dur,
                    )
                    continue

                seen_ids.add(shortcode)

                logger.info(
                    "Instagram candidate #%s [%s]: %s likes=%d duration=%.2fs",
                    tag,
                    label,
                    shortcode,
                    like_count,
                    duration,
                )

                path = _download_instagram_video(L, media, shortcode, delay)
                if not path:
                    total_stats["download_failed"] += 1
                    tag_stats["download_failed"] += 1
                    logger.warning(
                        "Instagram download failed for %s (#%s, %s)",
                        shortcode,
                        tag,
                        label,
                    )
                    continue

                total_duration += int(duration)
                title = _caption_text(media)
                user = media.get("user") or {}
                username = user.get("username") if isinstance(user, dict) else None
                author = username or "unknown"
                permalink = f"https://www.instagram.com/p/{shortcode}/"

                accepted.append(
                    {
                        "id": shortcode,
                        "title": title,
                        "selftext": "",
                        "top_comments": [],
                        "permalink": permalink,
                        "source_url": permalink,
                        "subreddit": "instagram",
                        "author": author,
                        "duration_sec": int(duration),
                        "local_path": str(path.resolve()),
                        "overlay_title": len(title) <= 75,
                        "score": like_count,
                        "upvote_ratio": 1.0,
                        "source": "instagram",
                    }
                )

                total_stats["accepted"] += 1
                tag_stats["accepted"] += 1

                logger.info(
                    "Accepted Instagram clip %s (#%s, %ds, likes=%d) — total %ds/%ds",
                    shortcode,
                    tag,
                    int(duration),
                    like_count,
                    total_duration,
                    warn_below_seconds,
                )

        logger.info(
            "Instagram tag summary #%s: raw=%d accepted=%d low_likes=%d bad_duration=%d "
            "already_used=%d duplicate_in_run=%d missing_shortcode=%d download_failed=%d",
            tag,
            tag_stats["raw_media_seen"],
            tag_stats["accepted"],
            tag_stats["low_likes"],
            tag_stats["bad_duration"],
            tag_stats["already_used"],
            tag_stats["duplicate_in_run"],
            tag_stats["missing_shortcode"],
            tag_stats["download_failed"],
        )

    if total_duration < warn_below_seconds:
        logger.warning(
            "Instagram TARGET NOT REACHED: sourced %ds of %ds desired for this split (%d%%).",
            total_duration,
            warn_below_seconds,
            int(total_duration / warn_below_seconds * 100) if warn_below_seconds else 0,
        )

    logger.info(
        "Instagram overall summary: raw=%d accepted=%d low_likes=%d bad_duration=%d "
        "already_used=%d duplicate_in_run=%d missing_shortcode=%d download_failed=%d",
        total_stats["raw_media_seen"],
        total_stats["accepted"],
        total_stats["low_likes"],
        total_stats["bad_duration"],
        total_stats["already_used"],
        total_stats["duplicate_in_run"],
        total_stats["missing_shortcode"],
        total_stats["download_failed"],
    )

    logger.info(
        "Instagram sourcing complete: %d clips, %ds total.",
        len(accepted),
        total_duration,
    )
    return accepted
