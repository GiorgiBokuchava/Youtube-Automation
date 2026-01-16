from __future__ import annotations

import os
import time
import random
import concurrent.futures
from multiprocessing import Process, Queue
from typing import List, Tuple, Optional

from yt_dlp import YoutubeDL

from src.youtube_automation.media.ffmpeg import ensure_ffmpeg
from src.youtube_automation.reddit.client import create_reddit_client
from src.youtube_automation.storage.sessions import get_used_video_ids
from src.youtube_automation.utils.paths import DOWNLOADS


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


def _extract_top_comments(submission, limit: int = 5, max_len: int = 180) -> list[str]:
    try:
        submission.comment_sort = "top"
        submission.comments.replace_more(limit=0)

        comments = []
        for c in submission.comments.list():
            body = getattr(c, "body", None)
            if not body:
                continue

            body = body.strip()
            if not body or body in ("[deleted]", "[removed]"):
                continue

            if len(body) > max_len:
                body = body[: max_len - 1] + "…"

            comments.append(body)
            if len(comments) >= limit:
                break

        return comments
    except Exception:
        return []


# yt-dlp worker
def _yt_dlp_worker(
    permalink: str, sid: str, ffmpeg_location: Optional[str], retq: Queue
):
    try:
        url = f"https://www.reddit.com{permalink}"
        opts = {
            "quiet": False,
            "noplaylist": True,
            "format": "bv*+ba/b[acodec!=none]",
            "merge_output_format": "mp4",
            "socket_timeout": 15,
            "retries": 3,
            "fragment_retries": 3,
            "extractor_retries": 2,
            "noprogress": True,
            "outtmpl": str(DOWNLOADS / f"{sid}.%(ext)s"),
        }

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


# Subreddit fetching
def _with_timeout(fn, name: str, what: str, timeout=20, retries=2, backoff=2.0):
    attempt = 0
    while attempt <= retries:
        attempt += 1
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(fn)
                return fut.result(timeout=timeout)
        except Exception:
            time.sleep(min(8.0, backoff ** (attempt - 1)))
    return []


def _fetch_feed(subreddit, mode: str, limit: int) -> List:
    name = subreddit.display_name
    if mode == "new":
        return _with_timeout(lambda: list(subreddit.new(limit=limit)), name, "new")
    if mode == "hot":
        return _with_timeout(lambda: list(subreddit.hot(limit=limit)), name, "hot")
    if mode == "rising":
        return _with_timeout(
            lambda: list(subreddit.rising(limit=limit)), name, "rising"
        )
    if mode == "top_day":
        return _with_timeout(
            lambda: list(subreddit.top(time_filter="day", limit=limit)), name, "top_day"
        )
    return []


# Public API
def source_videos(settings: dict) -> List[dict]:
    ffmpeg_location = ensure_ffmpeg()
    reddit = create_reddit_client()

    final_target_minutes = settings.get("final_target_duration", 0)
    final_target_seconds = int(final_target_minutes * 60)

    post_cfg = settings.get("post", {})
    min_dur = post_cfg.get("min_duration", 0)
    max_dur = post_cfg.get("max_duration", 10_000)
    min_score = post_cfg.get("min_score", 0)
    min_ratio = post_cfg.get("min_ratio", 0.0)

    context_cfg = settings.get("post_context", {})
    comments_limit = int(context_cfg.get("top_comments", 5))
    comment_max_len = int(context_cfg.get("comment_max_len", 180))
    include_selftext = bool(context_cfg.get("include_selftext", True))

    used_ids = get_used_video_ids(settings)
    accepted: List[dict] = []
    total_duration = 0

    subs = list(settings.get("subreddits", []))
    random.shuffle(subs)

    feed_plan: List[Tuple[str, int]] = [
        ("new", 200),
        ("hot", 120),
        ("top_day", 120),
        ("rising", 80),
    ]

    rounds_no_progress = 0

    while total_duration < final_target_seconds:
        round_progress = False

        for sub in subs:
            subreddit = reddit.subreddit(sub)

            for mode, limit in feed_plan:
                for submission in _fetch_feed(subreddit, mode, limit):
                    if submission.id in used_ids:
                        continue
                    used_ids.add(submission.id)

                    if not getattr(submission, "is_video", False):
                        continue
                    if float(submission.upvote_ratio or 0.0) < min_ratio:
                        continue

                    duration = _get_reddit_video_duration(submission)
                    if duration is None or not (min_dur <= duration <= max_dur):
                        continue

                    duration_factor = 50  # Additional score required per second
                    required_score = min_score + int(duration_factor * duration)

                    if submission.score < required_score:
                        continue

                    timeout = _compute_timeout_seconds(duration)
                    try:
                        path = _download_reddit_video(
                            submission, ffmpeg_location, timeout
                        )
                    except Exception:
                        continue

                    total_duration += duration
                    round_progress = True

                    top_comments = _extract_top_comments(
                        submission, limit=comments_limit, max_len=comment_max_len
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
                            "duration_sec": int(duration),
                            "local_path": path,
                            "overlay_title": len(submission.title or "") <= 75,
                            "score": int(submission.score),
                            "upvote_ratio": float(submission.upvote_ratio or 0.0),
                        }
                    )

                    time.sleep(random.uniform(0.25, 0.6))

                    if total_duration >= final_target_seconds:
                        break

            if total_duration >= final_target_seconds:
                break

        if not round_progress:
            rounds_no_progress += 1
            if rounds_no_progress >= 6:
                break
        else:
            rounds_no_progress = 0

    return accepted
