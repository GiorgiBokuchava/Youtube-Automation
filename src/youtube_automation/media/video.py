from __future__ import annotations

import os
import time
import random
import logging
from multiprocessing import Process, Queue
from typing import List, Tuple, Optional
from pathlib import Path

from yt_dlp import YoutubeDL

from youtube_automation.media.ffmpeg import ensure_ffmpeg
from youtube_automation.reddit.client import create_reddit_client, fetch_feed
from youtube_automation.storage.sessions import get_used_video_ids
from youtube_automation.utils.paths import DOWNLOADS
from youtube_automation.utils.text_sanitize import sanitize_plain_english_tts

logger = logging.getLogger(__name__)


# Helpers
def _get_reddit_video_duration(submission) -> Optional[int]:
    try:
        if (
            submission.is_video
            and submission.media
            and "reddit_video" in submission.media
        ):
            return int(submission.media["reddit_video"].get("duration"))
    except Exception:
        pass
    return None


def _cleanup_partials(stem: str) -> None:
    try:
        for p in DOWNLOADS.glob(f"{stem}*.part*"):
            p.unlink(missing_ok=True)
        for p in DOWNLOADS.glob(f"{stem}*.part-Frag*"):
            p.unlink(missing_ok=True)
    except Exception:
        pass


def _compute_timeout_seconds(duration_sec: int) -> int:
    return max(30, min(180, int(duration_sec * 3)))


def _word_count(text: str) -> int:
    """Whitespace-separated tokens (Reddit comment body)."""
    return len(text.split())


# Comprehensive word list used to filter top_comments before they can appear
# as TTS commentary.  Checked as a substring match against the lowercased text
# so partial matches (e.g. "kill" inside "killing") are also caught.
_COMMENT_BANNED: frozenset[str] = frozenset({
    # profanity
    "fuck", "fucking", "fucked", "fucker", "motherfuck", "motherfucker",
    "shit", "shitty", "bullshit",
    "bitch", "bitches",
    "cunt", "cunts",
    "ass", "asshole", "jackass", "dumbass", "smartass",
    "bastard",
    "dick", "dicks", "dickhead",
    "cock", "cocks",
    "pussy",
    "piss", "pissed",
    "damn", "damnit",
    "crap",
    "twat",
    "wanker", "wank",
    "arse",
    # slurs
    "nigger", "nigga", "nig",
    "faggot", "fag",
    "retard", "retarded",
    "spic", "chink", "gook", "kike", "wetback", "cracker",
    "tranny",
    "coon",
    # sexual content
    "slut", "slutty",
    "whore",
    "rape", "rapist", "raped", "raping",
    "molest", "molested",
    "porn", "porno", "pornhub",
    "nsfw",
    "sex", "sexy", "sexist",
    "horny",
    "dildo",
    "boobs", "tits", "titties",
    "penis", "vagina", "genitals",
    # violence / self-harm
    "kill", "killing", "kills", "killed", "killer",
    "murder", "murders", "murdered",
    "suicide", "suicidal",
    "die", "died", "dying",
    "dead", "death",
    "gore", "gory",
    "blood", "bloody",
    "stab", "stabbed",
    "shoot", "shot",
    "gun", "guns",
    "bomb", "bombing",
    "explode", "explosion",
    "hang", "hanged", "hanging",
    "torture", "torturing",
    "abuse", "abused", "abusive",
    "domestic",
    "assault",
    "attack", "attacked",
    "hurt", "injury", "injured",
    "fatal", "fatality",
    "accident",
    "disaster",
    "tragedy", "tragic",
    # drugs
    "drug", "drugs",
    "cocaine", "heroin", "meth", "crystal",
    "weed", "marijuana",
    "overdose",
    # hate / extremism
    "nazi", "nazis",
    "hitler",
    "terrorist", "terrorism",
    "racist", "racism",
    "hate crime",
})


def _comment_is_clean(text: str) -> bool:
    """Return True only if the text contains no banned words."""
    lower = text.lower()
    return not any(w in lower for w in _COMMENT_BANNED)


def _extract_comments_for_clip(
    submission,
    *,
    context_limit: int = 5,
    context_max_len: int = 180,
    context_max_words: int | None = 7,
) -> list[str]:
    """
    Collect up to *context_limit* top-sorted Reddit comments for a clip.

    Only keeps comments with at most *context_max_words* words (when set),
    truncates each to *context_max_len* chars, strips emojis/non-ASCII, and
    skips blank results.  Used as AI prompt context and stored in session JSON.
    """
    try:
        submission.comment_sort = "top"
        submission.comments.replace_more(limit=0)

        context: list[str] = []

        for c in submission.comments.list():
            if len(context) >= context_limit:
                break

            body = getattr(c, "body", "").strip()
            if not body or body in ("[deleted]", "[removed]"):
                continue

            if context_max_words is not None and _word_count(body) > context_max_words:
                continue

            if not _comment_is_clean(body):
                continue

            truncated = (
                body
                if len(body) <= context_max_len
                else body[: context_max_len - 3] + "..."
            )
            plain = sanitize_plain_english_tts(truncated)
            if plain:
                context.append(plain)

        return context
    except Exception:
        return []


# yt-dlp worker
def _yt_dlp_worker(
    permalink: str, sid: str, ffmpeg_location: Optional[str], retq: Queue
):
    try:
        url = f"https://www.reddit.com{permalink}"
        cookie_path = os.getenv("REDDIT_COOKIES_FILE")
        opts = {
            "quiet": False,
            "noplaylist": True,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "socket_timeout": 15,
            "retries": 3,
            "fragment_retries": 3,
            "extractor_retries": 2,
            "noprogress": True,
            "outtmpl": str(DOWNLOADS / f"{sid}.%(ext)s"),
        }

        opts.update(
            {
                "sleep_interval": 1.5,
                "max_sleep_interval": 4.0,
                "sleep_interval_requests": 1,
            }
        )

        if cookie_path and Path(cookie_path).exists():
            opts["cookiefile"] = cookie_path

        if ffmpeg_location:
            opts["ffmpeg_location"] = ffmpeg_location

        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            base = os.path.splitext(filename)[0]
            mp4_path = base + ".mp4"

        _cleanup_partials(sid)
        retq.put(("ok", mp4_path if os.path.exists(mp4_path) else filename))
    except Exception as e:
        retq.put(("err", f"{type(e).__name__}: {e}"))


def _download_reddit_video(
    submission, ffmpeg_location: Optional[str], timeout_sec: int
) -> str:
    q = Queue()
    p = Process(
        target=_yt_dlp_worker,
        args=(submission.permalink, submission.id, ffmpeg_location, q),
    )
    p.daemon = True
    p.start()
    p.join(timeout=timeout_sec)

    if p.is_alive():
        p.terminate()
        p.join(timeout=5)
        _cleanup_partials(submission.id)
        raise TimeoutError(f"download timeout after {timeout_sec}s")

    try:
        status, payload = q.get_nowait()
    except Exception:
        _cleanup_partials(submission.id)
        raise RuntimeError("download process ended without result")

    if status == "ok":
        return payload

    _cleanup_partials(submission.id)
    raise RuntimeError(payload)


# Public API
def source_videos(
    settings: dict,
    *,
    duration_cap_seconds: int | None = None,
    warn_below_seconds: int | None = None,
) -> List[dict]:
    ffmpeg_location = ensure_ffmpeg()
    reddit = create_reddit_client()

    final_target_minutes = settings.get("final_target_duration", 10)
    final_target_seconds = int(final_target_minutes * 60)

    post_cfg = settings.get("post", {})
    min_dur = post_cfg.get("min_duration", 0)
    max_dur = post_cfg.get("max_duration", 10_000)
    min_score = post_cfg.get("min_score", 0)
    min_ratio = post_cfg.get("min_ratio", 0.0)
    duration_score_factor = int(post_cfg.get("duration_score_factor", 20))

    over_source_pct = int(post_cfg.get("over_source_pct", 25))
    effective_target = int(final_target_seconds * (1 + over_source_pct / 100))
    if duration_cap_seconds is not None:
        effective_target = min(effective_target, int(duration_cap_seconds))

    context_cfg = settings.get("post_context", {})
    comments_limit = int(context_cfg.get("top_comments", 5))
    comment_max_len = int(context_cfg.get("comment_max_len", 180))
    _cmw = context_cfg.get("comment_max_words", 7)
    if _cmw in (None, False) or (isinstance(_cmw, int) and _cmw <= 0):
        context_max_words: int | None = None
    else:
        context_max_words = int(_cmw)
    include_selftext = bool(context_cfg.get("include_selftext", True))

    previously_used_ids = get_used_video_ids(settings)
    seen_ids: set[str] = set()
    accepted: List[dict] = []
    total_duration = 0

    subs = list(settings.get("subreddits", []))
    random.shuffle(subs)

    feed_plan: List[Tuple[str, int]] = [
        ("hot", 200),
        ("top_day", 200),
        ("new", 200),
        ("rising", 100),
    ]

    warn_threshold = (
        warn_below_seconds
        if warn_below_seconds is not None
        else final_target_seconds
    )

    logger.info(
        "Starting Reddit video sourcing: target=%d min (%ds), effective_target=%ds (over-source %d%%)",
        final_target_minutes,
        final_target_seconds,
        effective_target,
        over_source_pct,
    )
    logger.info("Targeting %d subreddits: %s", len(subs), ", ".join(subs))
    logger.info(
        "Filters: duration=%d-%ds, min_score=%d, min_ratio=%.2f, duration_score_factor=%d",
        min_dur,
        max_dur,
        min_score,
        min_ratio,
        duration_score_factor,
    )

    skipped_reasons: dict[str, int] = {
        "already_used": 0,
        "not_video": 0,
        "low_ratio": 0,
        "bad_duration": 0,
        "low_score": 0,
        "download_failed": 0,
    }

    for sub in subs:
        if total_duration >= effective_target:
            break

        subreddit = reddit.subreddit(sub)

        for mode, limit in feed_plan:
            if total_duration >= effective_target:
                break

            submissions = fetch_feed(subreddit, mode, limit)

            for submission in submissions:
                if total_duration >= effective_target:
                    break

                sid = submission.id
                if sid in seen_ids or sid in previously_used_ids:
                    skipped_reasons["already_used"] += 1
                    continue
                seen_ids.add(sid)

                if not getattr(submission, "is_video", False):
                    skipped_reasons["not_video"] += 1
                    continue
                if float(submission.upvote_ratio or 0.0) < min_ratio:
                    skipped_reasons["low_ratio"] += 1
                    continue

                duration = _get_reddit_video_duration(submission)
                if duration is None or not (min_dur <= duration <= max_dur):
                    skipped_reasons["bad_duration"] += 1
                    continue

                required_score = min_score + int(duration_score_factor * duration)
                if submission.score < required_score:
                    skipped_reasons["low_score"] += 1
                    continue

                timeout = _compute_timeout_seconds(duration)
                try:
                    path = _download_reddit_video(submission, ffmpeg_location, timeout)
                except Exception as exc:
                    skipped_reasons["download_failed"] += 1
                    logger.debug("Download failed for %s: %s", sid, exc)
                    continue

                total_duration += duration

                top_comments = _extract_comments_for_clip(
                    submission,
                    context_limit=comments_limit,
                    context_max_len=comment_max_len,
                    context_max_words=context_max_words,
                )

                accepted.append(
                    {
                        "id": submission.id,
                        "title": submission.title or "",
                        "selftext": (
                            (submission.selftext or "") if include_selftext else ""
                        ),
                        "top_comments": top_comments,
                        "permalink": f"https://www.reddit.com{submission.permalink}",
                        "source_url": submission.url,
                        "subreddit": submission.subreddit.display_name,
                        "author": (
                            getattr(submission.author, "name", "unknown")
                            if submission.author
                            else "unknown"
                        ),
                        "duration_sec": int(duration),
                        "local_path": path,
                        "overlay_title": len(submission.title or "") <= 75,
                        "score": int(submission.score),
                        "upvote_ratio": float(submission.upvote_ratio or 0.0),
                        "source": "reddit",
                    }
                )

                logger.info(
                    "Accepted clip %s from r/%s (%ds, score=%d) — total %ds/%ds",
                    sid,
                    submission.subreddit.display_name,
                    duration,
                    submission.score,
                    total_duration,
                    effective_target,
                )

                time.sleep(random.uniform(0.25, 0.6))

    logger.info(
        "Video sourcing complete: %d clips, %ds total (warn threshold %ds). " "Skipped: %s",
        len(accepted),
        total_duration,
        warn_threshold,
        ", ".join(f"{k}={v}" for k, v in skipped_reasons.items() if v > 0),
    )

    if total_duration < warn_threshold:
        logger.warning(
            "TARGET NOT REACHED: sourced %ds of %ds target (%d%%). "
            "Consider adding more subreddits or lowering score thresholds.",
            total_duration,
            warn_threshold,
            (
                int(total_duration / warn_threshold * 100)
                if warn_threshold
                else 0
            ),
        )

    return accepted
