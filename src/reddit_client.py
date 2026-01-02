import json
import os
import random
import sys
import time
from datetime import datetime, timezone, timedelta
from multiprocessing import Process, Queue
from pathlib import Path
from typing import List, Tuple, Optional

import concurrent.futures
import praw
import requests
import yaml
from dotenv import load_dotenv
from yt_dlp import YoutubeDL

# --------------------------
# Boot & Paths
# --------------------------
load_dotenv()

reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent=os.getenv("REDDIT_USER_AGENT"),
    requestor_kwargs={"timeout": 30},
)

with open("config/settings.yaml", "r", encoding="utf-8") as f:
    settings = yaml.safe_load(f) or {}

USED_PATH = Path("config/used.json")
DOWNLOADS = Path("downloads")
THUMBS = Path("thumbnails")
DOWNLOADS.mkdir(exist_ok=True)
THUMBS.mkdir(exist_ok=True)

# --------------------------
# Optional: Pillow for thumbnail processing
# --------------------------
try:
    from PIL import Image

    _PIL_RESAMPLE = getattr(
        getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC
    )
except ImportError:
    Image = None
    _PIL_RESAMPLE = None


def _require_pillow() -> None:
    if Image is None:
        print(
            "[fatal] Pillow is required for thumbnail processing. Install with: pip install pillow",
            file=sys.stderr,
        )
        sys.exit(1)


# --------------------------
# used.json (sessions & IDs)
# --------------------------
def _load_used_sessions() -> List[dict]:
    if USED_PATH.exists():
        try:
            with open(USED_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def _save_used_sessions(sessions: List[dict]) -> None:
    USED_PATH.parent.mkdir(exist_ok=True)
    with open(USED_PATH, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2)


def _get_all_used_ids() -> set:
    sessions = _load_used_sessions()
    used_ids = set()
    horizon_days = settings.get("used_horizon_days", 0)
    cutoff: Optional[datetime] = None
    if isinstance(horizon_days, int) and horizon_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=horizon_days)

    for session in sessions:
        if cutoff:
            try:
                created = datetime.fromisoformat(session.get("created_at", ""))
                if created < cutoff:
                    continue
            except Exception:
                pass
        for clip in session.get("clips", []):
            cid = clip.get("id")
            if cid:
                used_ids.add(cid)
    return used_ids


def _get_all_used_thumbnail_ids() -> set:
    sessions = _load_used_sessions()
    thumb_ids = set()
    for session in sessions:
        thumb = session.get("thumbnail", {})
        sid = thumb.get("submission_id")
        if sid:
            thumb_ids.add(sid)
    return thumb_ids


# --------------------------
# ffmpeg presence
# --------------------------
def _ensure_ffmpeg() -> Optional[str]:
    ffdir = os.getenv("FFMPEG_DIR")
    if ffdir:
        ffmpeg_bin = Path(ffdir, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        ffprobe_bin = Path(ffdir, "ffprobe.exe" if os.name == "nt" else "ffprobe")
        if ffmpeg_bin.exists() and ffprobe_bin.exists():
            return ffdir
    from shutil import which

    if which("ffmpeg") and which("ffprobe"):
        return None
    print(
        "[fatal] ffmpeg/ffprobe not found. Install and add to PATH, or set FFMPEG_DIR.",
        file=sys.stderr,
    )
    sys.exit(1)


# --------------------------
# Thumbnail helpers (still-only)
# --------------------------
def _guess_ext_from_headers(headers) -> Optional[str]:
    ctype = headers.get("Content-Type", "").lower()
    if "gif" in ctype or "video/" in ctype or "octet-stream" in ctype:
        return None
    if "image/jpeg" in ctype:
        return ".jpg"
    if "image/png" in ctype:
        return ".png"
    if "image/webp" in ctype:
        return ".webp"
    if ctype.startswith("image/"):
        return ".jpg"
    return None


def _pick_preview_still_with_dims(
    submission,
) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    try:
        if getattr(submission, "preview", None):
            imgs = submission.preview.get("images", [])
            if imgs:
                src = imgs[0].get("source", {})
                url = src.get("url")
                w = src.get("width")
                h = src.get("height")
                if url:
                    return (
                        url.replace("&amp;", "&"),
                        int(w) if w else None,
                        int(h) if h else None,
                    )
                res = imgs[0].get("resolutions", [])
                if res:
                    best = res[-1]
                    url = best.get("url")
                    w = best.get("width")
                    h = best.get("height")
                    if url:
                        return (
                            url.replace("&amp;", "&"),
                            int(w) if w else None,
                            int(h) if h else None,
                        )
    except Exception:
        pass
    try:
        u = submission.url
        if u and "i.redd.it" in u and not (u.endswith(".gif") or u.endswith(".gifv")):
            return u, None, None
    except Exception:
        pass
    thumb = getattr(submission, "thumbnail", "")
    if thumb and thumb not in ("self", "default", "nsfw"):
        return thumb, None, None
    return None, None, None


def _is_approx_16x9(w: int, h: int, tol: float = 0.01) -> bool:
    if not w or not h:
        return False
    aspect = w / h
    target = 16 / 9
    return abs(aspect - target) <= tol


def _download_image(url: str, dest_path: Path) -> Optional[Path]:
    try:
        headers = {"User-Agent": os.getenv("REDDIT_USER_AGENT", "thumb-downloader/0.1")}
        req = requests.get(url, headers=headers, timeout=20, stream=True)
        if req.status_code != 200:
            return None
        ext = _guess_ext_from_headers(req.headers)
        if not ext:
            return None
        final_path = dest_path.with_suffix(ext)
        with open(final_path, "wb") as f:
            for chunk in req.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return final_path
    except Exception:
        return None


def _make_youtube_thumb(
    src_path: Path, out_path: Path, size=(1280, 720)
) -> Optional[Path]:
    """
    Accept only images that are already ~16:9 and at least the target size.
    No cropping, no upscaling. Downscale to exactly 1280x720 if larger.
    """
    _require_pillow()
    try:
        with Image.open(src_path) as im:
            if getattr(im, "is_animated", False):
                im.seek(0)
            im = im.convert("RGB")

            if not _is_approx_16x9(im.width, im.height):
                return None
            if im.width < size[0] or im.height < size[1]:
                return None  # refuse to upscale

            if im.width != size[0] or im.height != size[1]:
                im = im.resize(size, _PIL_RESAMPLE)

            out_jpg = out_path.with_suffix(".jpg")
            im.save(out_jpg, format="JPEG", quality=90, optimize=True, progressive=True)
            return out_jpg
    except Exception as e:
        print(f"[thumb err] processing failed: {e}", file=sys.stderr)
        return None


def source_thumbnail() -> Optional[dict]:
    """
    Finds a still image and emits a YouTube-ready 1280x720 JPEG.
    Only accepts images already ~16:9 and >= configured min dims (no crop/upscale).
    Returns dict with {submission_id, path (yt), original_path, url} or None.
    """
    used_thumb_ids = _get_all_used_thumbnail_ids()
    subs_list = settings.get("subreddits", [])
    if not subs_list:
        print("[warn] No subreddits configured for thumbnails.", flush=True)
        return None

    # Stricter, thumbnail-specific defaults (override via settings['thumbnail'])
    thumb_cfg = settings.get("thumbnail", {})
    min_w = int(thumb_cfg.get("min_width", 1920))  # prefer native 1080p+
    min_h = int(thumb_cfg.get("min_height", 1080))
    min_score = int(thumb_cfg.get("min_score", 200))
    min_ratio = float(thumb_cfg.get("min_ratio", 0.90))
    allow_nsfw = bool(thumb_cfg.get("allow_nsfw", False))
    max_tries = int(thumb_cfg.get("max_tries", 10))

    tries = 0
    while tries < max_tries:
        tries += 1
        subreddit_name = random.choice(subs_list)
        subreddit = reddit.subreddit(subreddit_name)

        for submission in _fetch_feed(subreddit, "hot", 200):
            if submission.is_self or submission.id in used_thumb_ids:
                continue
            if not allow_nsfw and getattr(submission, "over_18", False):
                continue
            if getattr(submission, "score", 0) < min_score:
                continue
            try:
                ratio_val = (
                    float(submission.upvote_ratio)
                    if submission.upvote_ratio is not None
                    else 0.0
                )
                if ratio_val < min_ratio:
                    continue
            except Exception:
                continue

            url, w, h = _pick_preview_still_with_dims(submission)
            if not url:
                continue

            # Pre-screen: must already be ~16:9 and >= configured min dims
            if w and h:
                if not _is_approx_16x9(w, h):
                    continue
                if w < min_w or h < min_h:
                    continue

            base_dest = THUMBS / submission.id
            original_path = _download_image(url, base_dest)
            if not original_path:
                continue

            yt_jpg_path = _make_youtube_thumb(
                original_path, THUMBS / f"{submission.id}_yt"
            )
            if not yt_jpg_path:
                try:
                    original_path.unlink(missing_ok=True)
                except Exception:
                    pass
                continue

            print(
                f"[thumb] saved YouTube-ready: {yt_jpg_path}  (src: {submission.subreddit.display_name})"
            )
            return {
                "submission_id": submission.id,
                "path": str(yt_jpg_path),
                "original_path": str(original_path),
                "url": url,
            }

    print("No suitable thumbnail found.")
    return None


# --------------------------
# Video helpers
# --------------------------
def _get_reddit_video_duration(submission) -> Optional[int]:
    try:
        if (
            submission.is_video
            and submission.media
            and "reddit_video" in submission.media
        ):
            return int(submission.media["reddit_video"].get("duration"))
    except Exception as e:
        print("Error extracting post duration: " + str(e))
    return None


def _cleanup_partials(stem: str) -> None:
    try:
        for p in DOWNLOADS.glob(f"{stem}*.part*"):
            p.unlink(missing_ok=True)
        for p in DOWNLOADS.glob(f"{stem}*.part-Frag*"):
            p.unlink(missing_ok=True)
    except Exception:
        pass


def _yt_dlp_worker(permalink, sid, ffmpeg_location, ydl_opts, retq: Queue):
    try:
        url = f"https://www.reddit.com{permalink}"
        opts = dict(ydl_opts)
        opts["outtmpl"] = str(DOWNLOADS / f"{sid}.%(ext)s")
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


def _compute_timeout_seconds(duration_sec: int) -> int:
    return max(30, min(180, int(duration_sec * 3)))


def _download_reddit_video_mp4(
    submission, ffmpeg_location=None, timeout_sec=None
) -> str:
    stem = submission.id
    permalink = submission.permalink
    ydl_opts = {
        "quiet": False,
        "noplaylist": True,
        "format": "bv*+ba/b[acodec!=none]",
        "merge_output_format": "mp4",
        "socket_timeout": 15,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 2,
        "hls_prefer_native": False,
        "noprogress": True,
        "call_home": False,
        "sleep_interval_requests": 0.5,
        "max_sleep_interval_requests": 1.0,
        "prefer_free_formats": False,
        "continuedl": False,
        "keep_fragments": False,
    }
    q = Queue()
    p = Process(
        target=_yt_dlp_worker, args=(permalink, stem, ffmpeg_location, ydl_opts, q)
    )
    p.daemon = True
    p.start()
    p.join(timeout=timeout_sec or 120)
    if p.is_alive():
        p.terminate()
        p.join(timeout=5)
        _cleanup_partials(stem)
        raise TimeoutError(f"download timeout after {timeout_sec or 120}s")
    try:
        status, payload = q.get_nowait()
    except Exception:
        _cleanup_partials(stem)
        raise RuntimeError("download process ended without a result")
    if status == "ok":
        return payload
    _cleanup_partials(stem)
    raise RuntimeError(payload)


# --------------------------
# Robust subreddit listing
# --------------------------
def _with_timeout(fn, name: str, what: str, timeout=20, retries=2, backoff=2.0):
    attempt, last_err = 0, None
    while attempt <= retries:
        attempt += 1
        start = time.monotonic()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(fn)
                out = fut.result(timeout=timeout)
            elapsed = time.monotonic() - start
            print(f"[debug] fetch {what} r/{name} took {elapsed:.1f}s", flush=True)
            return out
        except concurrent.futures.TimeoutError as e:
            last_err = e
            print(
                f"[timeout] fetch {what} r/{name} >{timeout}s (attempt {attempt}/{retries+1})",
                flush=True,
            )
        except Exception as e:
            last_err = e
            print(
                f"[warn] fetch {what} r/{name} failed: {e} (attempt {attempt}/{retries+1})",
                flush=True,
            )
        time.sleep(min(8.0, backoff ** (attempt - 1)))
    print(f"[skip] listing r/{name} due to: {last_err}", flush=True)
    return []


def _fetch_feed(subreddit, mode: str, limit: int) -> List:
    name = subreddit.display_name
    if mode == "new":
        return _with_timeout(
            lambda: list(subreddit.new(limit=limit)), name, f"new({limit})"
        )
    if mode == "hot":
        return _with_timeout(
            lambda: list(subreddit.hot(limit=limit)), name, f"hot({limit})"
        )
    if mode == "rising":
        return _with_timeout(
            lambda: list(subreddit.rising(limit=limit)), name, f"rising({limit})"
        )
    if mode == "top_day":
        return _with_timeout(
            lambda: list(subreddit.top(time_filter="day", limit=limit)),
            name,
            f"top(day,{limit})",
        )
    return []


# --------------------------
# Video sourcing
# --------------------------
def source_videos() -> dict:
    ffmpeg_location = _ensure_ffmpeg()

    final_target_minutes = settings.get("final_target_duration", 0)
    final_target_seconds = int(final_target_minutes * 60)
    post_cfg = settings.get("post", {})
    post_min_duration = post_cfg.get("min_duration", 0)
    post_max_duration = post_cfg.get("max_duration", 10_000)
    post_min_score = post_cfg.get("min_score", 0)
    post_min_ratio = post_cfg.get("min_ratio", 0.0)

    print(
        f"[config] target={final_target_seconds}s "
        f"filters: score>={post_min_score} ratio>={post_min_ratio} "
        f"dur=[{post_min_duration},{post_max_duration}]s "
        f"subs={len(settings.get('subreddits', []))}",
        flush=True,
    )

    total_duration = 0
    accepted_clips: List[dict] = []
    seen_ids = _get_all_used_ids()

    subs: List[str] = list(settings.get("subreddits", []))
    random.shuffle(subs)

    feed_plan: List[Tuple[str, int]] = [
        ("new", 200),
        ("hot", 120),
        ("top_day", 120),
        ("rising", 80),
    ]

    print(f"Target total: {final_target_seconds}s", flush=True)

    rounds_no_progress = 0
    while total_duration < final_target_seconds:
        round_progress = False

        for subreddit_name in subs:
            if total_duration >= final_target_seconds:
                break

            subreddit = reddit.subreddit(subreddit_name)

            for mode, limit in feed_plan:
                if total_duration >= final_target_seconds:
                    break

                submissions = _fetch_feed(subreddit, mode, limit)
                for submission in submissions:
                    if submission.id in seen_ids:
                        print(f"[skip] {submission.id} already_used", flush=True)
                        continue
                    seen_ids.add(submission.id)

                    if not getattr(submission, "is_video", False):
                        print(f"[skip] {submission.id} not_video", flush=True)
                        continue
                    if submission.score < post_min_score:
                        print(
                            f"[skip] {submission.id} low_score={submission.score}",
                            flush=True,
                        )
                        continue
                    try:
                        ratio = (
                            float(submission.upvote_ratio)
                            if submission.upvote_ratio is not None
                            else 0.0
                        )
                        if ratio < post_min_ratio:
                            print(
                                f"[skip] {submission.id} low_ratio={ratio}", flush=True
                            )
                            continue
                    except Exception as e:
                        print(f"[skip] {submission.id} ratio_err={e}", flush=True)
                        continue

                    duration = _get_reddit_video_duration(submission)
                    if duration is None:
                        print(f"[skip] {submission.id} no_duration", flush=True)
                        continue
                    if not (post_min_duration <= duration <= post_max_duration):
                        print(
                            f"[skip] {submission.id} bad_duration={duration}",
                            flush=True,
                        )
                        continue

                    per_video_timeout = _compute_timeout_seconds(duration)
                    try:
                        local_path = _download_reddit_video_mp4(
                            submission,
                            ffmpeg_location=ffmpeg_location,
                            timeout_sec=per_video_timeout,
                        )
                    except Exception as e:
                        print(
                            f"[skip: download error] {submission.id} {e}",
                            file=sys.stderr,
                            flush=True,
                        )
                        time.sleep(random.uniform(0.25, 0.35))
                        continue

                    total_duration += duration
                    round_progress = True
                    overlay_title = len(submission.title or "") <= 75

                    clip_meta = {
                        "id": submission.id,
                        "title": submission.title or "",
                        "permalink": f"https://www.reddit.com{submission.permalink}",
                        "source_url": submission.url,
                        "subreddit": submission.subreddit.display_name,
                        "duration_sec": int(duration),
                        "local_path": local_path,
                        "overlay_title": overlay_title,
                        "score": int(submission.score),
                        "upvote_ratio": float(submission.upvote_ratio or 0.0),
                    }
                    accepted_clips.append(clip_meta)

                    print(
                        f"[ok] +{duration:>2}s total={total_duration:>4}s "
                        f"{submission.subreddit.display_name} {submission.id} "
                        f"title_overlay={overlay_title} path={local_path}",
                        flush=True,
                    )

                    time.sleep(random.uniform(0.25, 0.6))

                    if total_duration >= final_target_seconds:
                        break

        if not round_progress:
            rounds_no_progress += 1
            print(
                f"[info] No progress this round ({rounds_no_progress}/6).", flush=True
            )
            time.sleep(0.75)
            if rounds_no_progress >= 6:
                print(
                    "[stop] No eligible new posts found after multiple rounds. "
                    "Consider loosening filters or increasing subreddit list.",
                    flush=True,
                )
                break
        else:
            rounds_no_progress = 0

    return {
        "achieved_duration_sec": total_duration,
        "target_duration_sec": final_target_seconds,
        "clips": accepted_clips,
    }


# --------------------------
# Session write helper
# --------------------------
def _write_session(
    accepted_clips: List[dict], achieved_duration_sec: int, thumb_info: Optional[dict]
) -> None:
    sessions = _load_used_sessions()
    session_obj = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target_duration_sec": int(settings.get("final_target_duration", 0) * 60),
        "achieved_duration_sec": achieved_duration_sec,
        "num_clips": len(accepted_clips),
        "subreddits_scanned": list(set(settings.get("subreddits", []))),
        "thumbnail": thumb_info or {},
        "clips": accepted_clips,
    }
    sessions.append(session_obj)
    _save_used_sessions(sessions)
    print("[done] Session saved.", flush=True)


# --------------------------
# Convenience runners (no CLI)
# --------------------------
def run_videos():
    try:
        result = source_videos()
    except KeyboardInterrupt:
        print("\n[warn] Interrupted during video sourcing. Exiting.", flush=True)
        return

    clips = result["clips"]
    achieved = result["achieved_duration_sec"]

    if not clips:
        print("[done] No clips collected; not writing a session.", flush=True)
        return

    print("Building YouTube-ready thumbnail...", flush=True)
    thumb_info = None
    try:
        thumb_info = source_thumbnail()
    except KeyboardInterrupt:
        print(
            "\n[warn] Interrupted during thumbnail sourcing. Saving session without thumbnail.",
            flush=True,
        )

    _write_session(clips, achieved, thumb_info)


def run_thumbnail():
    try:
        info = source_thumbnail()
        if info:
            print(json.dumps(info, indent=2))
    except KeyboardInterrupt:
        print("\n[warn] Interrupted during thumbnail sourcing.", flush=True)


if __name__ == "__main__":
    # run_videos()
    run_thumbnail()
