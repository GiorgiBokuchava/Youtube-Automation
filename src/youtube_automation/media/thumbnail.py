from __future__ import annotations

import html
import os
import random
import time
import re
import logging
import concurrent.futures
from pathlib import Path
from typing import Optional, List

import requests
from PIL import Image

from youtube_automation.config.loader import BASE_DIR
from youtube_automation.reddit.client import create_reddit_client
from youtube_automation.storage.sessions import (
    get_used_thumbnail_ids,
    save_session,
    new_session,
)
from youtube_automation.utils.paths import THUMBS


logger = logging.getLogger(__name__)

_PIL_RESAMPLE = getattr(
    getattr(Image, "Resampling", Image),
    "LANCZOS",
    Image.BICUBIC,
)

_ASSETS_THUMB = BASE_DIR / "assets" / "thumbnail"
_EMOJI_ASSETS_DIR = _ASSETS_THUMB / "emojis"

_MIN_OVERLAY_SIDE_PX = 40

# Default emoji filenames when ``emoji_overlay.pool`` is omitted - keyed by ``commentary.theme``.
_THEME_DEFAULT_EMOJI_POOLS: dict[str, list[str]] = {
    "funny": [
        "laughing-with-tears-emoji.png",
        "silly-emoji.png",
        "smiling-emoji.png",
    ],
    "dramatic": [
        "shocked-emoji.png",
        "grimace-face-emoji.png",
        "anger-emoji.png",
    ],
    "cute": [
        "smiling-emoji.png",
        "laughing-with-tears-emoji.png",
        "silly-emoji.png",
    ],
}


def tl_tr_horizontal_room(
    canvas_w: int,
    margin: int,
    gap: int,
    arrow_w: int,
    emoji_w: int,
) -> bool:
    """True when top-left and top-right boxes leave ``gap`` between them."""
    return margin + arrow_w + gap <= canvas_w - margin - emoji_w


def _knockout_black_background(im_rgba: Image.Image, thresh: int) -> Image.Image:
    """Turn near-black pixels transparent (arrow PNG uses a black matte)."""
    out = im_rgba.copy()
    px = out.load()
    w, h = out.size
    for yy in range(h):
        for xx in range(w):
            r, g, b, a = px[xx, yy]
            if r <= thresh and g <= thresh and b <= thresh:
                px[xx, yy] = (r, g, b, 0)
    return out


def _resize_arrow_to_band(im: Image.Image, max_w: int, max_h: int) -> Image.Image:
    if im.width <= 0 or im.height <= 0:
        return im
    tw = min(im.width, max_w)
    th = max(1, int(im.height * tw / im.width))
    if th > max_h:
        th = max_h
        tw = max(1, int(im.width * th / im.height))
    tw = max(1, min(tw, max_w))
    th = max(1, min(th, max_h))
    return im.resize((tw, th), _PIL_RESAMPLE)


def _emoji_square_canvas(im: Image.Image, side: int) -> Image.Image:
    """Letterbox emoji into side×side RGBA tile."""
    im = im.convert("RGBA")
    thumb = im.copy()
    thumb.thumbnail((side, side), _PIL_RESAMPLE)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    ox = (side - thumb.width) // 2
    oy = (side - thumb.height) // 2
    canvas.paste(thumb, (ox, oy), thumb)
    return canvas


def _pick_emoji_file(settings: dict, emoji_cfg: dict) -> Optional[Path]:
    pool = emoji_cfg.get("pool")
    if isinstance(pool, list) and pool:
        candidates = [str(p).strip() for p in pool if str(p).strip()]
    else:
        theme = str((settings.get("commentary") or {}).get("theme", "funny")).lower().strip()
        candidates = list(_THEME_DEFAULT_EMOJI_POOLS.get(theme, _THEME_DEFAULT_EMOJI_POOLS["funny"]))
    random.shuffle(candidates)
    for name in candidates:
        path = _EMOJI_ASSETS_DIR / name
        if path.is_file():
            return path
    logger.warning(
        "Thumbnail emoji_overlay enabled but no emoji asset found under %s",
        _EMOJI_ASSETS_DIR,
    )
    return None


def _resolve_arrow_path(arrow_cfg: dict) -> Path:
    rel = str(arrow_cfg.get("asset") or "arrow-pointing-down.png").strip()
    p = Path(rel)
    if p.is_absolute():
        return p
    return _ASSETS_THUMB / p


def _apply_thumbnail_decorations(base_rgb: Image.Image, settings: dict) -> Image.Image:
    """Composite arrow / emoji on upper corners when enabled and space allows; never overlap."""
    cfg = settings.get("thumbnail") or {}
    arrow_cfg = cfg.get("arrow_overlay") or {}
    emoji_cfg = cfg.get("emoji_overlay") or {}

    want_arrow = bool(arrow_cfg.get("enabled", False))
    want_emoji = bool(emoji_cfg.get("enabled", False))

    if not want_arrow and not want_emoji:
        return base_rgb if base_rgb.mode == "RGB" else base_rgb.convert("RGB")

    w, h = base_rgb.size
    margin = max(16, int(min(w, h) * 0.022))
    gap = max(14, int(min(w, h) * 0.014))
    top_y_limit = min(h - margin, int(h * 0.40))
    band_h = max(1, top_y_limit - margin)

    arrow_orig: Optional[Image.Image] = None
    emoji_orig: Optional[Image.Image] = None

    if want_arrow:
        ap = _resolve_arrow_path(arrow_cfg)
        if ap.is_file():
            try:
                with Image.open(ap) as aim:
                    arrow_orig = aim.convert("RGBA")
                    if bool(arrow_cfg.get("knockout_black", True)):
                        thresh = int(arrow_cfg.get("black_thresh", 42))
                        arrow_orig = _knockout_black_background(arrow_orig, thresh)
            except Exception as exc:
                logger.warning("Thumbnail arrow asset unreadable (%s): %s", ap, exc)
                arrow_orig = None
        else:
            logger.warning("Thumbnail arrow_overlay enabled but missing file: %s", ap)

    if want_emoji:
        ef = _pick_emoji_file(settings, emoji_cfg)
        if ef:
            try:
                with Image.open(ef) as eim:
                    emoji_orig = eim.convert("RGBA")
            except Exception as exc:
                logger.warning("Thumbnail emoji asset unreadable (%s): %s", ef, exc)
                emoji_orig = None

    if arrow_orig is None:
        want_arrow = False
    if emoji_orig is None:
        want_emoji = False

    if not want_arrow and not want_emoji:
        return base_rgb if base_rgb.mode == "RGB" else base_rgb.convert("RGB")

    arrow_base_ratio = float(arrow_cfg.get("max_width_ratio", 0.20))
    emoji_base_ratio = float(emoji_cfg.get("size_ratio", 0.18))

    def build_arrow(sf: float) -> Optional[Image.Image]:
        if not want_arrow or not arrow_orig:
            return None
        max_arrow_w = max(1, int(w * arrow_base_ratio * sf))
        ar_im = _resize_arrow_to_band(arrow_orig, max_arrow_w, band_h)
        if (
            ar_im.width < _MIN_OVERLAY_SIDE_PX
            or ar_im.height < _MIN_OVERLAY_SIDE_PX
            or margin + ar_im.height > top_y_limit
            or margin + ar_im.width > w - margin
        ):
            return None
        return ar_im

    def build_emoji(sf: float) -> Optional[Image.Image]:
        if not want_emoji or not emoji_orig:
            return None
        d_target = max(1, int(w * emoji_base_ratio * sf))
        side = min(d_target, band_h, w - 2 * margin)
        em_im = _emoji_square_canvas(emoji_orig, side)
        if (
            em_im.width < _MIN_OVERLAY_SIDE_PX
            or margin + em_im.height > top_y_limit
            or margin + em_im.width > w - margin
        ):
            return None
        return em_im

    placed_arrow: Optional[Image.Image] = None
    placed_emoji: Optional[Image.Image] = None
    ax = ay = ex = ey = 0

    if want_arrow and want_emoji:
        sf = 1.0
        while sf >= 0.52:
            ar_im = build_arrow(sf)
            em_im = build_emoji(sf)
            if ar_im and em_im and tl_tr_horizontal_room(w, margin, gap, ar_im.width, em_im.width):
                placed_arrow, placed_emoji = ar_im, em_im
                ax, ay = margin, margin
                ex = w - margin - em_im.width
                ey = margin
                break
            sf *= 0.88

    if want_arrow and placed_arrow is None:
        sf = 1.0
        while sf >= 0.52:
            ar_im = build_arrow(sf)
            if ar_im:
                placed_arrow = ar_im
                ax, ay = margin, margin
                break
            sf *= 0.88

    if want_emoji and placed_emoji is None:
        sf = 1.0
        while sf >= 0.52:
            em_im = build_emoji(sf)
            if not em_im:
                sf *= 0.88
                continue
            ex_i = w - margin - em_im.width
            ey_i = margin
            if placed_arrow is None:
                placed_emoji = em_im
                ex, ey = ex_i, ey_i
                break
            if tl_tr_horizontal_room(w, margin, gap, placed_arrow.width, em_im.width):
                placed_emoji = em_im
                ex, ey = ex_i, ey_i
                break
            sf *= 0.88

    canvas = base_rgb.convert("RGBA")
    if placed_arrow:
        canvas.paste(placed_arrow, (ax, ay), placed_arrow)
    if placed_emoji:
        canvas.paste(placed_emoji, (ex, ey), placed_emoji)

    logger.info(
        "Thumbnail overlays applied: arrow=%s emoji=%s",
        placed_arrow is not None,
        placed_emoji is not None,
    )
    return canvas.convert("RGB")


DEFAULT_SEARCH_STAGES = [
    ("hot", 200),
    ("top_day", 200),
    ("new", 200),
    ("rising", 200),
]

FALLBACK_SEARCH_STAGES = [
    ("hot", 50),
    ("new", 50),
]


def _contains_banned_words(text: str, banned_words: List[str]) -> bool:
    if not text or not banned_words:
        return False

    clean_text = re.sub(r"[^\w\s]", " ", text.lower())
    words = clean_text.split()

    for banned_word in banned_words:
        bw = banned_word.lower()
        if bw in words:
            return True
        for w in words:
            if bw in w:
                return True

    return False


def _exceeds_max_words(text: str, max_words: int) -> bool:
    if not text or max_words <= 0:
        return False
    return len(re.findall(r"\b\w+\b", text.lower())) > max_words


def _is_acceptable_ratio(w: int, h: int, target_ratio: float, tolerance: float) -> bool:
    return abs((w / h) - target_ratio) <= tolerance


def _center_crop(im: Image.Image, target_ratio: float) -> Image.Image:
    w, h = im.width, im.height
    r = w / h

    if r > target_ratio:
        new_w = int(h * target_ratio)
        x = (w - new_w) // 2
        return im.crop((x, 0, x + new_w, h))

    new_h = int(w / target_ratio)
    y = (h - new_h) // 2
    return im.crop((0, y, w, y + new_h))


def _crop_and_resize(
    im: Image.Image,
    out_w: int,
    out_h: int,
    target_ratio: float,
    tolerance: float,
) -> Optional[Image.Image]:

    if not _is_acceptable_ratio(im.width, im.height, target_ratio, tolerance):
        return None

    cropped = _center_crop(im, target_ratio)
    return cropped.resize((out_w, out_h), _PIL_RESAMPLE)


def _composite_layout(target_w: int, target_h: int):
    bar_w = max(2, int(target_w * 0.02))
    col_w = (target_w - 2 * bar_w) // 3
    col_ratio = col_w / target_h
    return col_w, target_h, col_ratio, bar_w


def _create_composite_thumb(
    images: List[Image.Image],
    target_w: int,
    target_h: int,
    tolerance: float,
) -> Optional[Image.Image]:

    col_w, col_h, col_ratio, bar_w = _composite_layout(target_w, target_h)
    processed = []

    for im in images:
        col = _crop_and_resize(im, col_w, col_h, col_ratio, tolerance)
        if col:
            processed.append(col)
        if len(processed) == 3:
            break

    if len(processed) < 3:
        return None

    out = Image.new("RGB", (target_w, target_h), "white")

    x = 0
    for i, im in enumerate(processed):
        out.paste(im, (x, 0))
        x += col_w
        if i < 2:
            x += bar_w

    return out


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
        u = getattr(submission, "url", None) or ""
        if u:
            lu = u.lower()
            if "i.redd.it" in lu or any(
                lu.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")
            ):
                return u
        preview = getattr(submission, "preview", None) or {}
        images = preview.get("images") if isinstance(preview, dict) else None
        if images:
            src = images[0].get("source") or {}
            raw = src.get("url")
            if raw:
                return html.unescape(raw)
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


def _with_timeout(fn, timeout=20, retries=2, backoff=2.0):
    attempt = 0
    while attempt <= retries:
        attempt += 1
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(fn).result(timeout=timeout)
        except Exception:
            time.sleep(min(8.0, backoff ** (attempt - 1)))
    return []


def _fetch_feed(subreddit, mode: str, limit: int) -> List:
    if mode == "new":
        return _with_timeout(lambda: list(subreddit.new(limit=limit)))
    if mode == "hot":
        return _with_timeout(lambda: list(subreddit.hot(limit=limit)))
    if mode == "rising":
        return _with_timeout(lambda: list(subreddit.rising(limit=limit)))
    if mode == "top_day":
        return _with_timeout(
            lambda: list(subreddit.top(time_filter="day", limit=limit))
        )
    return []


def source_thumbnail(settings: dict) -> Optional[dict]:
    reddit = create_reddit_client()
    used_ids = get_used_thumbnail_ids(settings)

    subs = settings.get("subreddits", [])
    if not subs:
        return None

    cfg = settings.get("thumbnail", {})
    min_score = int(cfg.get("min_score", 0))
    min_ratio = float(cfg.get("min_ratio", 0.0))
    allow_nsfw = bool(cfg.get("allow_nsfw", False))
    target_w = int(cfg.get("target_width", 1920))
    target_h = int(cfg.get("target_height", 1080))
    tolerance = float(cfg.get("aspect_ratio_tolerance", 0.3))
    target_ratio = target_w / target_h
    banned_words = cfg.get("banned_words", [])
    max_title_words = int(cfg.get("max_title_words", 0))
    max_description_words = int(cfg.get("max_description_words", 0))

    search_stages = cfg.get("search_stages", DEFAULT_SEARCH_STAGES)

    random.shuffle(subs)

    for stage_name, limit in search_stages:

        for sub in subs:
            subreddit = reddit.subreddit(sub)

            try:
                submissions = _fetch_feed(subreddit, stage_name, limit)

                posts_checked = 0
                posts_skipped = 0

                for submission in submissions:
                    posts_checked += 1

                    if submission.is_self or submission.id in used_ids:
                        posts_skipped += 1
                        continue
                    if getattr(submission, "is_video", False):
                        posts_skipped += 1
                        continue
                    if not allow_nsfw and getattr(submission, "over_18", False):
                        posts_skipped += 1
                        continue
                    if submission.score < min_score:
                        posts_skipped += 1
                        continue
                    if float(submission.upvote_ratio or 0.0) < min_ratio:
                        posts_skipped += 1
                        continue

                    # Check content filters (banned words, max words)
                    if (
                        _contains_banned_words(submission.title or "", banned_words)
                        or (
                            max_title_words > 0
                            and _exceeds_max_words(
                                submission.title or "", max_title_words
                            )
                        )
                        or (
                            max_description_words > 0
                            and hasattr(submission, "selftext")
                            and submission.selftext
                            and _exceeds_max_words(
                                submission.selftext, max_description_words
                            )
                        )
                    ):
                        reason = []
                        if _contains_banned_words(submission.title or "", banned_words):
                            reason.append("banned words in title")
                        if max_title_words > 0 and _exceeds_max_words(
                            submission.title or "", max_title_words
                        ):
                            reason.append(f"title exceeds {max_title_words} words")
                        if (
                            max_description_words > 0
                            and hasattr(submission, "selftext")
                            and submission.selftext
                            and _exceeds_max_words(
                                submission.selftext, max_description_words
                            )
                        ):
                            reason.append(
                                f"description exceeds {max_description_words} words"
                            )

                        logger.debug("Skip %s: %s", submission.id, ", ".join(reason))
                        posts_skipped += 1
                        continue
                    url = _pick_image_url(submission)
                    if not url:
                        posts_skipped += 1
                        continue

                    THUMBS.mkdir(exist_ok=True)
                    original = _download_image(url, THUMBS / submission.id)
                    if not original:
                        continue

                    try:
                        with Image.open(original) as im:
                            im = im.convert("RGB")
                            out = _crop_and_resize(
                                im, target_w, target_h, target_ratio, tolerance
                            )
                    finally:
                        original.unlink(missing_ok=True)

                    if not out:
                        continue

                    out = _apply_thumbnail_decorations(out, settings)

                    out_path = THUMBS / f"{submission.id}_yt.jpg"
                    out.save(
                        out_path, "JPEG", quality=90, optimize=True, progressive=True
                    )

                    logger.info("Thumbnail sourced from r/%s (%s)", sub, stage_name)
                    return {
                        "submission_id": submission.id,
                        "path": str(out_path),
                        "original_path": None,
                        "url": url,
                    }

            except Exception as e:
                pass

    if target_ratio > 1.0:
        portraits = []
        fallback_used_ids = set()

        # Use stricter criteria for fallback (double normal requirements)
        fallback_min_score = min_score * 1.5
        fallback_min_ratio = min_ratio

        for stage_name, limit in FALLBACK_SEARCH_STAGES:
            for sub in subs:
                subreddit = reddit.subreddit(sub)

                try:
                    submissions = _fetch_feed(subreddit, stage_name, limit)
                    for submission in submissions:
                        if (
                            submission.is_self
                            or submission.id in used_ids
                            or submission.id in fallback_used_ids
                        ):
                            continue
                        if getattr(submission, "is_video", False):
                            continue
                        if not allow_nsfw and getattr(submission, "over_18", False):
                            continue
                        if submission.score < fallback_min_score:
                            continue
                        if float(submission.upvote_ratio or 0.0) < fallback_min_ratio:
                            continue
                        if _contains_banned_words(submission.title or "", banned_words):
                            continue
                        if max_title_words > 0 and _exceeds_max_words(
                            submission.title or "", max_title_words
                        ):
                            continue
                        if (
                            max_description_words > 0
                            and hasattr(submission, "selftext")
                            and submission.selftext
                        ):
                            if _exceeds_max_words(
                                submission.selftext, max_description_words
                            ):
                                continue

                        url = _pick_image_url(submission)
                        if not url:
                            continue

                        original = _download_image(url, THUMBS / submission.id)
                        if not original:
                            continue

                        try:
                            with Image.open(original) as im:
                                im = im.convert("RGB")
                                if im.width / im.height < 1.0:
                                    portraits.append(im.copy())
                                    fallback_used_ids.add(submission.id)
                        finally:
                            original.unlink(missing_ok=True)

                        if len(portraits) >= 3:
                            break
                except Exception:
                    continue
                if len(portraits) >= 3:
                    break
            if len(portraits) >= 3:
                break

        # Save fallback used IDs to session
        if portraits:
            for portrait_id in fallback_used_ids:
                thumb_session = {
                    "submission_id": portrait_id,
                    "path": f"fallback_portrait_{portrait_id}",
                    "original_path": None,
                    "url": f"fallback_portrait_{portrait_id}",
                }
                session = new_session({"thumbnail": thumb_session})
                save_session(session, {})

        composite = _create_composite_thumb(portraits, target_w, target_h, tolerance)
        if composite:
            composite = _apply_thumbnail_decorations(composite, settings)
            out_path = THUMBS / "composite_fallback.jpg"
            composite.save(
                out_path, "JPEG", quality=90, optimize=True, progressive=True
            )
            logger.info("Composite thumbnail created")
            return {
                "submission_id": "composite_fallback",
                "path": str(out_path),
                "original_path": None,
                "url": "composite_fallback",
            }

    logger.warning("No suitable thumbnail found")
    return None
