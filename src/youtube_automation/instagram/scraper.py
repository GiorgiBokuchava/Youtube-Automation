from __future__ import annotations

import logging
import random
import re
import time
from pathlib import Path
from typing import Generator

import instaloader

from youtube_automation.instagram.client import (
    SESSION_USERNAME_DEFAULT,
    build_loader,
    resolve_instagram_session_path,
)
from youtube_automation.storage.sessions import get_used_video_ids
from youtube_automation.utils.paths import DOWNLOADS

logger = logging.getLogger(__name__)

MEDIA_TYPE_VIDEO = 2

# Standalone abbreviations for 'generated-by-AI' callouts (comments/captions):
# - AI: English / international Latin
# - IA: Spanish, French, Portuguese, Italian (IA ~ AI)
# - II (Cyrillic): common Russian shorthand for AI
# Latin tokens use ASCII-letter boundaries so AID/FAIL/email-style substrings stay safe.
# German KI is omitted: Turkish uses standalone "ki" as a word -> too many false positives.
_LATIN_AI_MARKERS_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:AI|IA)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_CYRILLIC_II_MARKERS_RE = re.compile(r"(?<!\w)(?:ИИ)(?!\w)", re.UNICODE)


def _text_contains_ai_locale_marker(text: str) -> bool:
    """True when ``text`` contains AI / IA / Cyrillic II token."""
    if not text or not text.strip():
        return False
    if _LATIN_AI_MARKERS_RE.search(text):
        return True
    return bool(_CYRILLIC_II_MARKERS_RE.search(text))


def _caption_or_comments_signal_ai(*, caption: str, comment_texts: list[str]) -> bool:
    """True if caption or any sampled comment carries an AI locale marker."""
    if _text_contains_ai_locale_marker(caption):
        return True
    return any(_text_contains_ai_locale_marker(t) for t in comment_texts)


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


def iter_profile_video_posts(
    L: instaloader.Instaloader,
    username: str,
    limit: int,
) -> Generator[instaloader.Post, None, None]:
    """Yield up to ``limit`` video posts from a profile timeline (newest first)."""
    try:
        profile = instaloader.Profile.from_username(L.context, username)
    except instaloader.exceptions.ProfileNotExistsException:
        logger.warning("Instagram account not found: @%s", username)
        return
    except instaloader.exceptions.PrivateProfileNotFollowedException:
        logger.warning("Instagram account private or not followed: @%s", username)
        return
    except Exception as exc:
        logger.warning("Instagram profile @%s unavailable: %s", username, exc)
        return

    yielded = 0
    try:
        for post in profile.get_posts():
            try:
                if not post.is_video:
                    continue
            except (KeyError, TypeError):
                continue
            yielded += 1
            yield post
            if yielded >= limit:
                return
    except instaloader.exceptions.TooManyRequestsException:
        logger.warning(
            "Instagram rate limited while scanning @%s — waiting 60s...",
            username,
        )
        time.sleep(60)
    except Exception as exc:
        logger.warning("Instagram posts iteration failed for @%s: %s", username, exc)


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
    shortcode: str,
    delay: float,
    *,
    media: dict | None = None,
    post: instaloader.Post | None = None,
) -> Path | None:
    try:
        resolved: instaloader.Post
        if post is not None:
            resolved = post
        elif media is not None:
            resolved = instaloader.Post.from_iphone_struct(L.context, media)
        else:
            logger.debug("Instagram download skipped %s: no media or post", shortcode)
            return None
        L.download_post(resolved, target=shortcode)
        path = _pick_downloaded_mp4(shortcode)
        if path:
            time.sleep(delay)
        return path
    except Exception as exc:
        logger.debug("Instagram download failed for %s: %s", shortcode, exc)
        return None


def _top_instagram_comment_texts(
    L: instaloader.Instaloader,
    shortcode: str,
    *,
    media: dict | None = None,
    post: instaloader.Post | None = None,
    limit: int = 5,
) -> list[str]:
    """First ``limit`` comment bodies from Instaloader (may be fewer); empty on failure."""
    try:
        if post is not None:
            resolved = post
        elif media is not None:
            resolved = instaloader.Post.from_iphone_struct(L.context, media)
        else:
            return []
        texts: list[str] = []
        for comment in resolved.get_comments():
            texts.append((comment.text or "").strip())
            if len(texts) >= limit:
                break
        return texts
    except Exception as exc:
        logger.debug("Failed to fetch comments for %s: %s", shortcode, exc)
        return []


def source_instagram_videos(
    settings: dict,
    *,
    duration_cap_seconds: int,
    warn_below_seconds: int,
    exclude_ids: set[str] | None = None,
    max_clips: int | None = None,
) -> list[dict]:
    """
    Download Instagram reel/video posts matching channel ``instagram`` settings.

    Discovers candidates from configured hashtags (top/recent) and/or seed accounts
    (profile video timeline). Filters: likes, duration, rejection when caption or any of
    the top sampled comments contain multilingual AI abbreviations (AI, IA, Cyrillic ИИ),
    dedupe.

    ``duration_cap_seconds`` caps total *accepted* clip duration.

    When ``max_clips`` is set, sourcing stops once that many clips are accepted
    (still subject to filters). Duration cap is bumped so short compilations can
    reach the clip target without hitting duration first.
    """
    ig = settings.get("instagram") or {}
    hashtags = [
        str(h).lstrip("#").strip() for h in (ig.get("hashtags") or []) if str(h).strip()
    ]
    accounts = [
        str(a).lstrip("@").strip() for a in (ig.get("accounts") or []) if str(a).strip()
    ]
    if not hashtags and not accounts:
        logger.warning(
            "Instagram sourcing disabled: no hashtags or accounts configured.",
        )
        return []

    min_likes = int(ig.get("min_likes", 5000))
    min_dur = float(ig.get("min_duration", 3))
    max_dur = float(ig.get("max_duration", 60))

    if max_clips is not None and max_clips > 0:
        duration_cap_seconds = max(
            duration_cap_seconds,
            max_clips * max(30, int(max_dur)) + 120,
        )
    section_mode = str(ig.get("section", "both"))
    limit_per_hashtag = int(ig.get("limit_per_hashtag", 100))
    limit_per_account = int(ig.get("limit_per_account", limit_per_hashtag))
    delay = float(ig.get("delay", 2.0))
    session_username = str(ig.get("session_username", SESSION_USERNAME_DEFAULT))

    previously_used = get_used_video_ids(settings)
    if exclude_ids:
        previously_used = set(previously_used).union(exclude_ids)
    seen_ids: set[str] = set()
    accepted: list[dict] = []
    total_duration = 0
    stop_early = False

    random.shuffle(hashtags)
    random.shuffle(accounts)

    logger.info(
        "Instagram sourcing: cap=%ds, warn_below=%ds, hashtags=%d, accounts=%d, "
        "likes>=%d duration=%.1f-%.1fs section=%s limit_ht=%d limit_acct=%d previously_used=%d",
        duration_cap_seconds,
        warn_below_seconds,
        len(hashtags),
        len(accounts),
        min_likes,
        min_dur,
        max_dur,
        section_mode,
        limit_per_hashtag,
        limit_per_account,
        len(previously_used),
    )
    if hashtags:
        logger.info("Instagram hashtags after shuffle: %s", ", ".join(hashtags))
    if accounts:
        logger.info("Instagram accounts after shuffle: %s", ", ".join(accounts))

    session_path = resolve_instagram_session_path(session_username=session_username)
    L = build_loader(
        session_path,
        download_dir=DOWNLOADS,
        session_username=session_username,
        instagram_settings=ig,
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
        "ai_keyword_flag": 0,
        "download_failed": 0,
        "accepted": 0,
    }

    def consume_candidate(
        *,
        kind_tag: str,
        section_label: str,
        shortcode: str,
        like_count: int,
        duration: float,
        caption: str,
        author: str,
        media: dict | None,
        post: instaloader.Post | None,
        bucket_stats: dict[str, int],
    ) -> None:
        nonlocal total_duration, stop_early
        slot = f"{kind_tag} [{section_label}]"

        if stop_early:
            return

        total_stats["raw_media_seen"] += 1
        bucket_stats["raw_media_seen"] += 1

        if not shortcode:
            total_stats["missing_shortcode"] += 1
            bucket_stats["missing_shortcode"] += 1
            logger.debug(
                "Instagram skip %s: missing shortcode | likes=%s duration=%s",
                slot,
                like_count,
                duration,
            )
            return

        if shortcode in seen_ids:
            total_stats["duplicate_in_run"] += 1
            bucket_stats["duplicate_in_run"] += 1
            logger.debug(
                "Instagram skip %s: duplicate in this run %s",
                slot,
                shortcode,
            )
            return

        if shortcode in previously_used:
            total_stats["already_used"] += 1
            bucket_stats["already_used"] += 1
            logger.debug(
                "Instagram skip %s: already used %s",
                slot,
                shortcode,
            )
            return

        if like_count < min_likes:
            total_stats["low_likes"] += 1
            bucket_stats["low_likes"] += 1
            logger.debug(
                "Instagram skip %s: low likes %s likes=%d < %d",
                slot,
                shortcode,
                like_count,
                min_likes,
            )
            return

        if not (min_dur <= duration <= max_dur):
            total_stats["bad_duration"] += 1
            bucket_stats["bad_duration"] += 1
            logger.debug(
                "Instagram skip %s: bad duration %s duration=%.2fs not in %.2f-%.2fs",
                slot,
                shortcode,
                duration,
                min_dur,
                max_dur,
            )
            return

        logger.debug("Instagram sampling comments for %s", shortcode)
        comment_texts = _top_instagram_comment_texts(
            L,
            shortcode,
            media=media,
            post=post,
            limit=5,
        )

        if _caption_or_comments_signal_ai(caption=caption, comment_texts=comment_texts):
            total_stats["ai_keyword_flag"] += 1
            bucket_stats["ai_keyword_flag"] += 1
            logger.info(
                "Instagram skip %s: AI/IA/Cyrillic-II marker in caption or comments for %s",
                slot,
                shortcode,
            )
            return

        seen_ids.add(shortcode)

        logger.info(
            "Instagram candidate %s: %s likes=%d duration=%.2fs",
            slot,
            shortcode,
            like_count,
            duration,
        )

        path = _download_instagram_video(
            L,
            shortcode,
            delay,
            media=media,
            post=post,
        )
        if not path:
            total_stats["download_failed"] += 1
            bucket_stats["download_failed"] += 1
            logger.warning(
                "Instagram download failed for %s (%s)",
                shortcode,
                slot,
            )
            return

        total_duration += int(duration)
        title = caption
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
        bucket_stats["accepted"] += 1

        if max_clips is not None and len(accepted) >= max_clips:
            stop_early = True

        logger.info(
            "Accepted Instagram clip %s (%s, %ds, likes=%d) — total %ds/%ds",
            shortcode,
            slot,
            int(duration),
            like_count,
            total_duration,
            warn_below_seconds,
        )

    for tag in hashtags:
        if stop_early or total_duration >= duration_cap_seconds:
            break

        tag_stats = {
            "raw_media_seen": 0,
            "missing_shortcode": 0,
            "duplicate_in_run": 0,
            "already_used": 0,
            "low_likes": 0,
            "bad_duration": 0,
            "ai_keyword_flag": 0,
            "download_failed": 0,
            "accepted": 0,
        }

        logger.info("Instagram tag start: #%s", tag)

        for section_key, label in sections_to_scan:
            if stop_early or total_duration >= duration_cap_seconds:
                break

            logger.info("Instagram tag #%s scanning section=%s", tag, label)

            for media in iter_hashtag_section(L, tag, section_key, limit_per_hashtag):
                if stop_early or total_duration >= duration_cap_seconds:
                    break

                shortcode = media.get("code") or ""
                like_count = int(media.get("like_count") or 0)
                duration = float(media.get("video_duration") or 0.0)
                caption = _caption_text(media)
                user = media.get("user") or {}
                username = user.get("username") if isinstance(user, dict) else None
                author = username or "unknown"

                consume_candidate(
                    kind_tag=f"#{tag}",
                    section_label=label,
                    shortcode=shortcode,
                    like_count=like_count,
                    duration=duration,
                    caption=caption,
                    author=author,
                    media=media,
                    post=None,
                    bucket_stats=tag_stats,
                )

        logger.info(
            "Instagram tag summary #%s: raw=%d accepted=%d low_likes=%d bad_duration=%d "
            "ai_kw=%d already_used=%d duplicate_in_run=%d missing_shortcode=%d "
            "download_failed=%d",
            tag,
            tag_stats["raw_media_seen"],
            tag_stats["accepted"],
            tag_stats["low_likes"],
            tag_stats["bad_duration"],
            tag_stats["ai_keyword_flag"],
            tag_stats["already_used"],
            tag_stats["duplicate_in_run"],
            tag_stats["missing_shortcode"],
            tag_stats["download_failed"],
        )

    for username in accounts:
        if stop_early or total_duration >= duration_cap_seconds:
            break

        acct_stats = {
            "raw_media_seen": 0,
            "missing_shortcode": 0,
            "duplicate_in_run": 0,
            "already_used": 0,
            "low_likes": 0,
            "bad_duration": 0,
            "ai_keyword_flag": 0,
            "download_failed": 0,
            "accepted": 0,
        }

        logger.info("Instagram account start: @%s", username)

        for post in iter_profile_video_posts(L, username, limit_per_account):
            if stop_early or total_duration >= duration_cap_seconds:
                break

            shortcode = post.shortcode
            like_count = int(post.likes or 0)
            duration = float(post.video_duration or 0.0)
            caption = post.caption or ""
            author = post.owner_username or username

            consume_candidate(
                kind_tag=f"@{username}",
                section_label="timeline",
                shortcode=shortcode,
                like_count=like_count,
                duration=duration,
                caption=caption,
                author=author,
                media=None,
                post=post,
                bucket_stats=acct_stats,
            )

        logger.info(
            "Instagram account summary @%s: raw=%d accepted=%d low_likes=%d bad_duration=%d "
            "ai_kw=%d already_used=%d duplicate_in_run=%d missing_shortcode=%d "
            "download_failed=%d",
            username,
            acct_stats["raw_media_seen"],
            acct_stats["accepted"],
            acct_stats["low_likes"],
            acct_stats["bad_duration"],
            acct_stats["ai_keyword_flag"],
            acct_stats["already_used"],
            acct_stats["duplicate_in_run"],
            acct_stats["missing_shortcode"],
            acct_stats["download_failed"],
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
        "ai_kw=%d already_used=%d duplicate_in_run=%d missing_shortcode=%d "
        "download_failed=%d",
        total_stats["raw_media_seen"],
        total_stats["accepted"],
        total_stats["low_likes"],
        total_stats["bad_duration"],
        total_stats["ai_keyword_flag"],
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
