from __future__ import annotations

import os
import random
import time
import re
import concurrent.futures
from pathlib import Path
from typing import Optional, List

import requests
from PIL import Image, ImageFilter

from src.youtube_automation.reddit.client import create_reddit_client
from src.youtube_automation.storage.sessions import get_used_thumbnail_ids
from src.youtube_automation.utils.paths import THUMBS


DEBUG = False

# NOTE could add 3 images separated by white bars instead of one image with blur pads


def log(msg: str) -> None:
    if DEBUG:
        print(msg, flush=True)


def _contains_banned_words(text: str, banned_words: List[str]) -> bool:
    if not text or not banned_words:
        return False

    clean_text = re.sub(r"[^\w\s]", " ", text.lower())
    words = clean_text.split()

    for banned_word in banned_words:
        banned_clean = banned_word.lower()
        if banned_clean in words:
            return True
        for word in words:
            if banned_clean in word:
                return True

    return False


def _exceeds_max_words(text: str, max_words: int) -> bool:
    if not text or max_words <= 0:
        return False

    words = re.findall(r"\b\w+\b", text.lower())
    return len(words) > max_words


_PIL_RESAMPLE = getattr(
    getattr(Image, "Resampling", Image),
    "LANCZOS",
    Image.BICUBIC,
)


def _is_acceptable_ratio(w: int, h: int, target_ratio: float, tolerance: float) -> bool:
    r = w / h
    return abs(r - target_ratio) <= tolerance


def _center_crop(im: Image.Image, target_ratio: float) -> Image.Image:
    w, h = im.width, im.height
    r = w / h

    if r > target_ratio:
        new_w = int(h * target_ratio)
        x = (w - new_w) // 2
        return im.crop((x, 0, x + new_w, h))
    else:
        new_h = int(w / target_ratio)
        y = (h - new_h) // 2
        return im.crop((0, y, w, y + new_h))


def _make_thumb(
    im: Image.Image, target_w: int, target_h: int, target_ratio: float, tolerance: float
) -> Optional[Image.Image]:
    w, h = im.width, im.height

    if not _is_acceptable_ratio(w, h, target_ratio, tolerance):
        log(
            f"[skip] unacceptable_ratio {w}x{h} (ratio: {w/h:.2f}, target: {target_ratio:.2f}±{tolerance})"
        )
        return None

    cropped = _center_crop(im, target_ratio)
    return cropped.resize((target_w, target_h), _PIL_RESAMPLE)


def _create_composite_thumb(
    portrait_images: List[Image.Image], target_w: int, target_h: int
) -> Image.Image:
    """Create composite thumbnail from 3 portrait images with white bars"""
    if len(portrait_images) < 3:
        return None

    # Calculate dimensions for 3 equal columns with white bars
    column_width = target_w // 3
    bar_width = target_w // 20  # Small white bars between images

    # Resize all portrait images to fit height and maintain aspect ratio
    resized_images = []
    for img in portrait_images:
        # Calculate width to maintain aspect ratio while fitting target height
        aspect_ratio = img.width / img.height
        new_width = int(target_h * aspect_ratio)
        # Limit to column width minus some padding
        new_width = min(new_width, column_width - 10)
        resized = img.resize((new_width, target_h), _PIL_RESAMPLE)
        resized_images.append(resized)

    # Create white background
    composite = Image.new("RGB", (target_w, target_h), "white")

    # Calculate positions to center 3 images
    current_x = 0
    for i, img in enumerate(resized_images[:3]):  # Use only first 3 images
        # Center vertically
        y_pos = (target_h - img.height) // 2
        # Center horizontally in column
        x_pos = current_x + (column_width - img.width) // 2

        composite.paste(img, (x_pos, y_pos))
        current_x += column_width

        # Add white bar after each image except last
        if i < 2:
            current_x += bar_width

    return composite


def _guess_ext_from_headers(headers) -> Optional[str]:
    ctype = headers.get("Content-Type", "").lower()
    if "gif" in ctype or "octet-stream" in ctype:
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


def _pick_image_url(submission) -> Optional[str]:
    try:
        u = submission.url
        if u and any(
            u.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")
        ):
            return u
    except Exception:
        pass

    return None


def _download_image(url: str, dest: Path) -> Optional[Path]:
    try:
        headers = {"User-Agent": os.getenv("REDDIT_USER_AGENT", "thumb-downloader/1.0")}
        r = requests.get(url, headers=headers, timeout=20, stream=True)
        if r.status_code != 200:
            return None

        ext = _guess_ext_from_headers(r.headers)
        if not ext:
            return None

        out = dest.with_suffix(ext)
        with open(out, "wb") as f:
            for c in r.iter_content(8192):
                if c:
                    f.write(c)

        return out
    except Exception:
        return None


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


def source_thumbnail(settings: dict) -> Optional[dict]:
    reddit = create_reddit_client()
    used_ids = get_used_thumbnail_ids()

    subs = settings.get("subreddits", [])
    if not subs:
        print("[warn] No subreddits configured for thumbnails.")
        return None

    cfg = settings.get("thumbnail", {})
    min_score = int(cfg.get("min_score", 0))
    min_ratio = float(cfg.get("min_ratio", 0.0))
    allow_nsfw = bool(cfg.get("allow_nsfw", False))
    target_w = int(cfg.get("target_width", 1920))
    target_h = int(cfg.get("target_height", 1080))
    target_ratio = target_w / target_h
    tolerance = float(cfg.get("aspect_ratio_tolerance", 0.3))
    banned_words = cfg.get("banned_words", [])
    max_title_words = int(cfg.get("max_title_words", 0))
    max_description_words = int(cfg.get("max_description_words", 0))

    search_stages = [
        ("hot", 100),  # Stage 1: Hot content (highest quality)
        ("top_day", 50),  # Stage 2: Top content (proven quality)
        ("new", 100),  # Stage 3: New content (fresh posts)
        ("rising", 50),  # Stage 4: Rising content (trending)
    ]

    random.shuffle(subs)

    if DEBUG:
        print(f"[debug] Starting comprehensive search across {len(subs)} subreddits...")
        print(
            f"[debug] Search criteria: score>={min_score}, ratio>={min_ratio}, tolerance={tolerance}"
        )
        print(
            f"[debug] Target dimensions: {target_w}x{target_h} (ratio: {target_ratio:.2f})"
        )
    else:
        print(f"[thumb] Starting comprehensive search across {len(subs)} subreddits...")

    for stage_name, limit in search_stages:
        if DEBUG:
            print(f"[debug] === STAGE: {stage_name} (limit: {limit}) ===")
        else:
            print(f"[thumb] Stage: {stage_name} (limit: {limit})")

        for sub in subs:
            subreddit = reddit.subreddit(sub)
            if DEBUG:
                print(f"[debug] Scanning r/{subreddit.display_name} ({stage_name})")
            else:
                log(f"[scan] r/{subreddit.display_name} ({stage_name})")

            try:
                submissions = _fetch_feed(subreddit, stage_name, limit)
                if DEBUG:
                    print(
                        f"[debug] Found {len(submissions)} posts in r/{subreddit.display_name} ({stage_name})"
                    )

                posts_checked = 0
                posts_skipped = 0

                for submission in submissions:
                    posts_checked += 1

                    if submission.is_self or submission.id in used_ids:
                        if DEBUG:
                            log(f"[skip] {submission.id}: self post or already used")
                        posts_skipped += 1
                        continue
                    if getattr(submission, "is_video", False):
                        if DEBUG:
                            log(f"[skip] {submission.id}: video post")
                        posts_skipped += 1
                        continue
                    if not allow_nsfw and getattr(submission, "over_18", False):
                        if DEBUG:
                            log(f"[skip] {submission.id}: NSFW content")
                        posts_skipped += 1
                        continue
                    if submission.score < min_score:
                        if DEBUG:
                            log(
                                f"[skip] {submission.id}: score {submission.score} < {min_score}"
                            )
                        posts_skipped += 1
                        continue
                    if float(submission.upvote_ratio or 0.0) < min_ratio:
                        if DEBUG:
                            log(
                                f"[skip] {submission.id}: ratio {submission.upvote_ratio} < {min_ratio}"
                            )
                        posts_skipped += 1
                        continue

                    # Check for banned words in title
                    if _contains_banned_words(submission.title or "", banned_words):
                        if DEBUG:
                            log(f"[skip] {submission.id}: banned words in title")
                        posts_skipped += 1
                        continue

                    # Check max words in title
                    if max_title_words > 0 and _exceeds_max_words(
                        submission.title or "", max_title_words
                    ):
                        if DEBUG:
                            log(
                                f"[skip] {submission.id}: title exceeds {max_title_words} words"
                            )
                        posts_skipped += 1
                        continue

                    # Check max words in description (if available)
                    if (
                        max_description_words > 0
                        and hasattr(submission, "selftext")
                        and submission.selftext
                    ):
                        if _exceeds_max_words(
                            submission.selftext, max_description_words
                        ):
                            if DEBUG:
                                log(
                                    f"[skip] {submission.id}: description exceeds {max_description_words} words"
                                )
                            posts_skipped += 1
                            continue

                    url = _pick_image_url(submission)
                    if not url:
                        if DEBUG:
                            log(f"[skip] {submission.id}: no valid image URL")
                        posts_skipped += 1
                        continue

                    THUMBS.mkdir(exist_ok=True)
                    base = THUMBS / submission.id

                    original = _download_image(url, base)
                    if not original:
                        if DEBUG:
                            log(f"[skip] {submission.id}: download failed")
                        posts_skipped += 1
                        continue

                    try:
                        with Image.open(original) as im:
                            if getattr(im, "is_animated", False):
                                im.seek(0)
                            im = im.convert("RGB")
                            out_im = _make_thumb(
                                im, target_w, target_h, target_ratio, tolerance
                            )
                    except Exception as e:
                        if DEBUG:
                            log(
                                f"[skip] {submission.id}: image processing failed - {e}"
                            )
                        original.unlink(missing_ok=True)
                        posts_skipped += 1
                        continue

                    if out_im is None:
                        if DEBUG:
                            log(f"[skip] {submission.id}: aspect ratio rejected")
                        posts_skipped += 1
                        original.unlink(missing_ok=True)
                        continue

                    out_path = (THUMBS / f"{submission.id}_yt").with_suffix(".jpg")
                    out_im.save(
                        out_path, "JPEG", quality=90, optimize=True, progressive=True
                    )

                    # Remove original uncropped image, keep only YT-ready version
                    original.unlink(missing_ok=True)

                    if DEBUG:
                        print(
                            f"[debug] SUCCESS: Found suitable thumbnail from r/{sub} ({stage_name})"
                        )
                        print(
                            f"[debug] Stats: {posts_checked} checked, {posts_skipped} skipped in this subreddit"
                        )
                    else:
                        print(
                            f"[thumb] SUCCESS: Found suitable thumbnail from r/{sub} ({stage_name})"
                        )
                    return {
                        "submission_id": submission.id,
                        "path": str(out_path),
                        "original_path": None,  # Original deleted
                        "url": url,
                    }

                if DEBUG and posts_checked > 0:
                    print(
                        f"[debug] r/{subreddit.display_name} ({stage_name}): {posts_checked} checked, {posts_skipped} skipped"
                    )

            except Exception as e:
                if DEBUG:
                    print(f"[debug] Failed to fetch from r/{sub}: {e}")
                else:
                    log(f"[error] Failed to fetch from r/{sub}: {e}")
                continue

    if DEBUG:
        print(
            f"[debug] No suitable thumbnail found after searching all {len(search_stages)} stages across {len(subs)} subreddits."
        )
    else:
        print(
            f"[thumb] No suitable thumbnail found after searching all {len(search_stages)} stages across {len(subs)} subreddits."
        )

    # Fallback: Try to create composite from 3 portrait images if target is landscape
    if target_ratio > 1.0:  # Only for landscape targets
        print("[thumb] Attempting fallback: creating composite from portrait images...")
        portrait_images = []

        # Collect portrait images from all subreddits (reusing existing logic)
        for stage_name, limit in [
            ("hot", 50),
            ("new", 50),
        ]:  # Limited search for fallback
            for sub in subs[:10]:  # Limit to first 10 subreddits for speed
                subreddit = reddit.subreddit(sub)
                if DEBUG:
                    print(
                        f"[debug] Fallback scan: r/{subreddit.display_name} ({stage_name})"
                    )

                try:
                    submissions = _fetch_feed(subreddit, stage_name, limit)
                    for submission in submissions:
                        if submission.is_self or submission.id in used_ids:
                            continue
                        if getattr(submission, "is_video", False):
                            continue
                        if not allow_nsfw and getattr(submission, "over_18", False):
                            continue
                        if submission.score < min_score:
                            continue
                        if float(submission.upvote_ratio or 0.0) < min_ratio:
                            continue
                        if _contains_banned_words(submission.title or "", banned_words):
                            continue
                        if max_title_words > 0 and _exceeds_max_words(
                            submission.title or "", max_title_words
                        ):
                            if DEBUG:
                                log(
                                    f"[skip] {submission.id}: title exceeds {max_title_words} words"
                                )
                            continue
                        if (
                            max_description_words > 0
                            and hasattr(submission, "selftext")
                            and submission.selftext
                        ):
                            if _exceeds_max_words(
                                submission.selftext, max_description_words
                            ):
                                if DEBUG:
                                    log(
                                        f"[skip] {submission.id}: description exceeds {max_description_words} words"
                                    )
                                continue

                        url = _pick_image_url(submission)
                        if not url:
                            continue

                        THUMBS.mkdir(exist_ok=True)
                        base = THUMBS / submission.id
                        original = _download_image(url, base)
                        if not original:
                            continue

                        try:
                            with Image.open(original) as im:
                                if getattr(im, "is_animated", False):
                                    im.seek(0)
                                im = im.convert("RGB")

                                # Check if this is a portrait image (ratio < 1.0)
                                w, h = im.width, im.height
                                if w / h < 1.0:  # Portrait
                                    portrait_images.append(im)
                                    if DEBUG:
                                        print(
                                            f"[debug] Found portrait image: {submission.id} ({w}x{h})"
                                        )

                                    # Clean up original since we're just collecting
                                    original.unlink(missing_ok=True)

                                    if len(portrait_images) >= 3:
                                        break

                        except Exception:
                            original.unlink(missing_ok=True)
                            continue

                        if len(portrait_images) >= 3:
                            break
                    if len(portrait_images) >= 3:
                        break

                    if DEBUG:
                        print(
                            f"[debug] Collected {len(portrait_images)} portrait images"
                        )

                except Exception as e:
                    if DEBUG:
                        print(f"[debug] Failed to fetch from r/{sub}: {e}")
                    else:
                        log(f"[error] Failed to fetch from r/{sub}: {e}")
                    continue

        # Create composite if we have enough portrait images
        if len(portrait_images) >= 3:
            try:
                composite = _create_composite_thumb(portrait_images, target_w, target_h)
                if composite:
                    out_path = (THUMBS / "composite_fallback").with_suffix(".jpg")
                    composite.save(
                        out_path, "JPEG", quality=90, optimize=True, progressive=True
                    )

                    print(
                        f"[thumb] SUCCESS: Created composite thumbnail from {len(portrait_images)} portrait images"
                    )
                    return {
                        "submission_id": "composite_fallback",
                        "path": str(out_path),
                        "original_path": None,
                        "url": "composite_fallback",
                    }
            except Exception as e:
                if DEBUG:
                    print(f"[debug] Composite creation failed: {e}")
                else:
                    print(f"[thumb] Composite creation failed: {e}")

    print(f"[thumb] Fallback failed - no suitable thumbnail found.")
    return None
