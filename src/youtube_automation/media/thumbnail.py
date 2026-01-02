from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageFilter

from src.youtube_automation.reddit.client import create_reddit_client
from src.youtube_automation.storage.sessions import get_used_thumbnail_ids
from src.youtube_automation.utils.paths import THUMBS


DEBUG = False


def log(msg: str) -> None:
    if DEBUG:
        print(msg, flush=True)


_PIL_RESAMPLE = getattr(
    getattr(Image, "Resampling", Image),
    "LANCZOS",
    Image.BICUBIC,
)


TARGET_W = 1920
TARGET_H = 1080
TARGET_RATIO = TARGET_W / TARGET_H


def _is_extreme_ratio(w: int, h: int) -> bool:
    r = w / h
    return r > 2.2 or r < 0.45


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


def _make_thumb(im: Image.Image) -> Optional[Image.Image]:
    w, h = im.width, im.height
    r = w / h

    if _is_extreme_ratio(w, h):
        log(f"[skip] extreme_ratio {w}x{h}")
        return None

    if r < TARGET_RATIO:
        fg_scale = TARGET_H / h
        fg_w = int(w * fg_scale)
        fg_h = TARGET_H

        fg = im.resize((fg_w, fg_h), _PIL_RESAMPLE)

        bg = im.resize((TARGET_W, TARGET_H), _PIL_RESAMPLE)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=40))

        x = (TARGET_W - fg_w) // 2
        bg.paste(fg, (x, 0))
        return bg

    cropped = _center_crop(im, TARGET_RATIO)
    return cropped.resize((TARGET_W, TARGET_H), _PIL_RESAMPLE)


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
    max_tries = int(cfg.get("max_tries", 10))

    tries = 0
    while tries < max_tries:
        tries += 1
        subreddit = reddit.subreddit(random.choice(subs))
        log(f"[scan] r/{subreddit.display_name}")

        for submission in subreddit.hot(limit=200):
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
                    out_im = _make_thumb(im)
            except Exception:
                original.unlink(missing_ok=True)
                continue

            if out_im is None:
                original.unlink(missing_ok=True)
                continue

            out_path = (THUMBS / f"{submission.id}_yt").with_suffix(".jpg")
            out_im.save(out_path, "JPEG", quality=90, optimize=True, progressive=True)

            print(f"[thumb] saved: {out_path}")
            return {
                "submission_id": submission.id,
                "path": str(out_path),
                "original_path": str(original),
                "url": url,
            }

    print("[thumb] No suitable thumbnail found.")
    return None
