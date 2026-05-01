from __future__ import annotations

import os
import random
import time
import re
import logging
import concurrent.futures
from pathlib import Path
from typing import Optional, List

import requests
from PIL import Image, ImageDraw

from youtube_automation.reddit.client import create_reddit_client
from youtube_automation.storage.sessions import (
    get_used_thumbnail_ids,
    save_session,
    new_session,
)
from youtube_automation.utils.paths import THUMBS


logger = logging.getLogger(__name__)
_YOLO_MODELS: dict[str, object] = {}

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
_ASSETS_ROOT = Path(__file__).resolve().parents[3] / "assets" / "thumbnail"
_EMOJI_DIR = _ASSETS_ROOT / "emojis"
_ARROW_PATH = _ASSETS_ROOT / "arrow.png"


def _rect_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int], pad: int = 0) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (
        (ax2 + pad) <= (bx1 - pad)
        or (bx2 + pad) <= (ax1 - pad)
        or (ay2 + pad) <= (by1 - pad)
        or (by2 + pad) <= (ay1 - pad)
    )


def _pick_overlay_rect(
    canvas_w: int,
    canvas_h: int,
    overlay_w: int,
    overlay_h: int,
    blocked: list[tuple[int, int, int, int]],
    occupied: list[tuple[int, int, int, int]],
    margin: int,
) -> tuple[int, int, int, int] | None:
    positions = [
        (margin, margin),  # top-left
        (canvas_w - overlay_w - margin, margin),  # top-right
        (margin, canvas_h - overlay_h - margin),  # bottom-left
        (canvas_w - overlay_w - margin, canvas_h - overlay_h - margin),  # bottom-right
        ((canvas_w - overlay_w) // 2, margin),  # top-center
        ((canvas_w - overlay_w) // 2, canvas_h - overlay_h - margin),  # bottom-center
        (margin, (canvas_h - overlay_h) // 2),  # mid-left
        (canvas_w - overlay_w - margin, (canvas_h - overlay_h) // 2),  # mid-right
    ]
    for x, y in positions:
        rect = (x, y, x + overlay_w, y + overlay_h)
        if any(_rect_overlap(rect, b, pad=margin // 2) for b in blocked):
            continue
        if any(_rect_overlap(rect, o, pad=margin // 2) for o in occupied):
            continue
        return rect
    return None


def _draw_fallback_arrow(base: Image.Image, rect: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = rect
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)
    draw = ImageDraw.Draw(base)
    shaft_w = max(4, int(min(w, h) * 0.12))
    color = (255, 64, 64)
    head = [
        (x1 + int(w * 0.68), y1 + int(h * 0.12)),
        (x1 + int(w * 0.95), y1 + int(h * 0.50)),
        (x1 + int(w * 0.68), y1 + int(h * 0.88)),
    ]
    draw.polygon(head, fill=color)
    draw.line(
        [
            (x1 + int(w * 0.18), y1 + int(h * 0.50)),
            (x1 + int(w * 0.76), y1 + int(h * 0.50)),
        ],
        fill=color,
        width=shaft_w,
    )


def _draw_fallback_emoji(base: Image.Image, rect: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = rect
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)
    draw = ImageDraw.Draw(base)
    face = (255, 222, 89)
    eye = (30, 30, 30)
    mouth = (180, 60, 60)
    draw.ellipse([x1, y1, x2, y2], fill=face)
    ex = int(w * 0.22)
    ey = int(h * 0.34)
    er = max(2, int(min(w, h) * 0.07))
    draw.ellipse([x1 + ex - er, y1 + ey - er, x1 + ex + er, y1 + ey + er], fill=eye)
    draw.ellipse(
        [x2 - ex - er, y1 + ey - er, x2 - ex + er, y1 + ey + er], fill=eye
    )
    mx1 = x1 + int(w * 0.25)
    mx2 = x2 - int(w * 0.25)
    my1 = y1 + int(h * 0.56)
    my2 = y2 - int(h * 0.20)
    draw.arc([mx1, my1, mx2, my2], start=15, end=165, fill=mouth, width=max(2, er))


def _detect_major_object_boxes(
    image: Image.Image, cfg: dict
) -> list[tuple[int, int, int, int]]:
    model_name = str(cfg.get("yolo_model", "yolov8n.pt"))
    conf = float(cfg.get("yolo_confidence", 0.35))
    max_objects = max(1, int(cfg.get("max_major_objects", 3)))
    min_area_ratio = float(cfg.get("major_object_min_area_ratio", 0.03))
    try:
        from ultralytics import YOLO
    except Exception as e:
        logger.warning("YOLO unavailable for thumbnail overlays: %s", e)
        return []

    try:
        model = _YOLO_MODELS.get(model_name)
        if model is None:
            model = YOLO(model_name)
            _YOLO_MODELS[model_name] = model
        result = model.predict(source=image, conf=conf, verbose=False, max_det=10)[0]
    except Exception as e:
        logger.warning("YOLO detection failed; placing overlays without detections: %s", e)
        return []

    boxes = getattr(getattr(result, "boxes", None), "xyxy", None)
    if boxes is None:
        return []
    area_floor = image.width * image.height * min_area_ratio
    detected: list[tuple[int, tuple[int, int, int, int]]] = []
    for row in boxes.tolist():
        x1, y1, x2, y2 = [int(v) for v in row[:4]]
        if x2 <= x1 or y2 <= y1:
            continue
        area = (x2 - x1) * (y2 - y1)
        if area < area_floor:
            continue
        detected.append((area, (x1, y1, x2, y2)))
    detected.sort(key=lambda t: t[0], reverse=True)
    return [b for _, b in detected[:max_objects]]


def _resolve_emoji_path(cfg: dict) -> Path | None:
    emoji_cfg = cfg.get("emoji_overlay", {}) or {}
    pool = emoji_cfg.get("pool") or []
    candidates: list[Path] = []
    for item in pool:
        p = Path(str(item))
        if not p.is_absolute():
            p = _EMOJI_DIR / p.name
        candidates.append(p)
    if not candidates and _EMOJI_DIR.exists():
        candidates = sorted(_EMOJI_DIR.glob("*.png"))
    existing = [p for p in candidates if p.exists()]
    if not existing:
        return None
    return random.choice(existing)


def _apply_thumbnail_overlays(base: Image.Image, cfg: dict) -> None:
    arrow_cfg = cfg.get("arrow_overlay", {}) or {}
    emoji_cfg = cfg.get("emoji_overlay", {}) or {}
    arrow_enabled = bool(arrow_cfg.get("enabled", False))
    emoji_enabled = bool(emoji_cfg.get("enabled", False))
    if not arrow_enabled and not emoji_enabled:
        return

    major_boxes = _detect_major_object_boxes(base, cfg)
    occupied: list[tuple[int, int, int, int]] = []
    margin = max(12, int(min(base.width, base.height) * 0.03))

    if arrow_enabled:
        arrow_ratio = float(arrow_cfg.get("size_ratio", 0.20))
        aw = max(48, int(base.width * arrow_ratio))
        ah = max(48, int(aw * 0.85))
        arrow_rect = _pick_overlay_rect(
            base.width, base.height, aw, ah, major_boxes, occupied, margin
        )
        if arrow_rect:
            try:
                if _ARROW_PATH.exists():
                    with Image.open(_ARROW_PATH) as arrow_im:
                        arrow_im = arrow_im.convert("RGBA").resize((aw, ah), _PIL_RESAMPLE)
                        base.paste(arrow_im, (arrow_rect[0], arrow_rect[1]), arrow_im)
                else:
                    _draw_fallback_arrow(base, arrow_rect)
                occupied.append(arrow_rect)
            except Exception as e:
                logger.warning("Arrow overlay failed: %s", e)
        else:
            logger.warning("No safe placement found for arrow overlay")

    if emoji_enabled:
        emoji_ratio = float(emoji_cfg.get("size_ratio", 0.20))
        ew = max(48, int(base.width * emoji_ratio))
        eh = ew
        emoji_rect = _pick_overlay_rect(
            base.width, base.height, ew, eh, major_boxes, occupied, margin
        )
        if emoji_rect is None:
            logger.warning("No safe placement found for emoji overlay")
            return
        emoji_path = _resolve_emoji_path(cfg)
        try:
            if emoji_path is None:
                _draw_fallback_emoji(base, emoji_rect)
                return
            with Image.open(emoji_path) as emoji_im:
                emoji_im = emoji_im.convert("RGBA").resize((ew, eh), _PIL_RESAMPLE)
                base.paste(emoji_im, (emoji_rect[0], emoji_rect[1]), emoji_im)
        except Exception as e:
            logger.warning("Emoji overlay failed for %s: %s", emoji_path, e)
            _draw_fallback_emoji(base, emoji_rect)


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


_PIL_RESAMPLE = getattr(
    getattr(Image, "Resampling", Image),
    "LANCZOS",
    Image.BICUBIC,
)


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

                    _apply_thumbnail_overlays(out, cfg)
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
            _apply_thumbnail_overlays(composite, cfg)
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
