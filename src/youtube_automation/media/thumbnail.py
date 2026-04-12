from __future__ import annotations

import html
import math
import os
import re
import logging
from pathlib import Path
from typing import Optional, List

import requests
from PIL import Image

from youtube_automation.reddit.client import create_reddit_client, fetch_feed
from youtube_automation.storage.sessions import get_used_thumbnail_ids
from youtube_automation.utils.paths import THUMBS


logger = logging.getLogger(__name__)

_THUMBNAIL_ASSETS = Path("assets/thumbnail")
_ARROW_PNG_PATH = _THUMBNAIL_ASSETS / "arrow-pointing-down.png"
_EMOJIS_DIR = _THUMBNAIL_ASSETS / "emojis"
_YOLO_MODEL_CACHE = None

# Map commentary theme / channel niche keywords → emoji filenames (stem only for
# easy matching; extension handled at load time).
_THEME_EMOJI_POOLS: dict[str, list[str]] = {
    "funny":    ["laughing-with-tears-emoji", "silly-emoji", "smiling-emoji"],
    "cute":     ["smiling-emoji", "silly-emoji"],
    "dramatic": ["shocked-emoji", "grimace-face-emoji", "anger-emoji"],
    "road":     ["shocked-emoji", "grimace-face-emoji", "anger-emoji"],
    "fail":     ["shocked-emoji", "grimace-face-emoji"],
    "rage":     ["anger-emoji", "shocked-emoji"],
}

# ---------------------------------------------------------------------------
# YOLO / thumbnail overlay helpers
# ---------------------------------------------------------------------------

def _load_yolo_model():
    global _YOLO_MODEL_CACHE
    if _YOLO_MODEL_CACHE is None:
        from ultralytics import YOLO  # type: ignore
        _YOLO_MODEL_CACHE = YOLO("yolov8n.pt")
    return _YOLO_MODEL_CACHE


def _choose_arrow_start(cx: float, cy: float, width: int, height: int, margin: int = 24):
    """Return a screen corner diagonally opposite the detected object."""
    if cx >= width / 2 and cy < height / 2:
        return margin, height - margin
    if cx < width / 2 and cy < height / 2:
        return width - margin, height - margin
    if cx >= width / 2 and cy >= height / 2:
        return margin, margin
    return width - margin, margin


def _find_tip_in_down_arrow(sprite: Image.Image):
    """
    Locate the pixel-level tip of a down-pointing arrow PNG.
    Returns (cropped_sprite, tip_x, tip_y) or None if the sprite has no opaque pixels.
    """
    alpha = sprite.split()[-1]
    bbox = alpha.getbbox()
    if bbox is None:
        return None
    cropped = sprite.crop(bbox)
    alpha_c = cropped.split()[-1]
    a_bbox = alpha_c.getbbox()
    if a_bbox is None:
        return None
    max_y = a_bbox[3] - 1
    row = alpha_c.crop((0, max_y, cropped.width, max_y + 1))
    xs = [x for x in range(cropped.width) if row.getpixel((x, 0)) > 0]
    tip_x = (xs[0] + xs[-1]) / 2 if xs else cropped.width / 2
    return cropped, tip_x, float(max_y)


def _choose_arrow_target_outside_box(
    bx1: float, by1: float, bx2: float, by2: float,
    obj_cx: float, obj_cy: float,
    start: tuple,
    pad: int = 0,
) -> tuple[int, int]:
    """
    Pick the bounding-box corner nearest the arrow *start*, then nudge it *pad*
    pixels further outside the box so the tip doesn't cover the subject.
    """
    start_x, start_y = start
    corner_x = bx1 if start_x < obj_cx else bx2
    corner_y = by1 if start_y < obj_cy else by2
    vx, vy = corner_x - obj_cx, corner_y - obj_cy
    dist = math.hypot(vx, vy)
    if dist == 0:
        nx = -1.0 if start_x < obj_cx else 1.0
        ny = -1.0 if start_y < obj_cy else 1.0
    else:
        nx, ny = vx / dist, vy / dist
    return int(round(corner_x + nx * pad)), int(round(corner_y + ny * pad))


def _arrow_lengths(image: Image.Image, arrow_cfg: dict) -> tuple[int, int]:
    """
    Return (max_length, min_length) in pixels relative to the image's shorter
    side so the arrow looks the same regardless of resolution.

    Defaults are calibrated so the arrow occupies ~32 % / ~16 % of the shorter
    side — roughly 345 / 173 px on a 1920×1080 thumbnail.  Both values can be
    overridden in YAML via ``arrow_overlay.max_length_ratio`` /
    ``arrow_overlay.min_length_ratio``.
    """
    short_side = min(image.width, image.height)
    max_ratio = float(arrow_cfg.get("max_length_ratio", 0.32))
    min_ratio = float(arrow_cfg.get("min_length_ratio", 0.16))
    return int(short_side * max_ratio), int(short_side * min_ratio)


def _overlay_arrow_png(
    base_rgb: Image.Image,
    arrow_sprite: Image.Image,
    start: tuple,
    end: tuple,
    aim_at: tuple,
    max_length: int = 345,
    min_length: int = 173,
) -> None:
    """
    Composite a PNG arrow onto *base_rgb* (in-place).

    The tip is pinned at *end*.  The shaft is rotated to aim at *aim_at*
    (typically the object centre), which keeps the arrow pointing naturally
    toward the subject even when the tip sits on a corner of the bounding box.
    """
    x1, y1 = start
    x2, y2 = end
    length = math.hypot(x2 - x1, y2 - y1)
    if length == 0:
        return

    target_length = max(min_length, min(max_length, length))
    prepared = _find_tip_in_down_arrow(arrow_sprite)
    if prepared is None:
        return

    cropped, tip_x, tip_y = prepared
    scale = target_length / max(1.0, tip_y)
    new_w = max(8, int(cropped.width * scale))
    new_h = max(8, int(cropped.height * scale))
    scaled = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)
    tip_x *= scale
    tip_y *= scale

    # Angle the shaft toward aim_at (object centre) rather than raw start→end.
    ax, ay = aim_at
    angle = 90.0 - math.degrees(math.atan2(ay - y2, ax - x2))
    rotated = scaled.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)

    # Transform tip coordinates through the same rotation.
    c0x, c0y = scaled.width / 2.0, scaled.height / 2.0
    vx, vy = tip_x - c0x, tip_y - c0y
    rad = math.radians(angle)
    rvx = vx * math.cos(rad) + vy * math.sin(rad)
    rvy = -vx * math.sin(rad) + vy * math.cos(rad)
    c1x, c1y = rotated.width / 2.0, rotated.height / 2.0
    rotated_tip_x = c1x + rvx
    rotated_tip_y = c1y + rvy

    paste_x = int(round(x2 - rotated_tip_x))
    paste_y = int(round(y2 - rotated_tip_y))

    layer = Image.new("RGBA", base_rgb.size, (0, 0, 0, 0))
    layer.paste(rotated, (paste_x, paste_y), rotated)
    base_rgb.paste(Image.alpha_composite(base_rgb.convert("RGBA"), layer).convert("RGB"))


def _rect_intersection_area(a: tuple, b: tuple) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    return max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)


def _find_empty_space(
    all_boxes: list,
    img_w: int,
    img_h: int,
    arrow_start: tuple,
    item_w: int = 60,
    item_h: int = 60,
    max_overlap_ratio: float = 0.4,
) -> Optional[tuple]:
    """
    Scan the image on a coarse grid for a position (centre-point) that avoids
    detected objects, sits in the opposite quadrant from the arrow start, and
    favours the upper part of the frame.
    """
    best_pt = None
    best_score = -float("inf")
    cx, cy = img_w / 2.0, img_h / 2.0
    arrow_qx = arrow_start[0] > cx
    arrow_qy = arrow_start[1] > cy
    step_x = max(10, img_w // 25)
    step_y = max(10, img_h // 25)
    emoji_area = item_w * item_h

    for y in range(item_h, img_h - item_h, step_y):
        for x in range(item_w, img_w - item_w, step_x):
            if (x > cx) == arrow_qx and (y > cy) == arrow_qy:
                continue
            candidate = (x - item_w / 2.0, y - item_h / 2.0, x + item_w / 2.0, y + item_h / 2.0)
            overlap = sum(_rect_intersection_area(candidate, b) for b in all_boxes)
            if overlap / emoji_area > max_overlap_ratio:
                continue
            dist_sq = (x - cx) ** 2 + (y - cy) ** 2
            score = dist_sq - y * (img_w * 2) - (overlap / emoji_area) * (img_w * img_h)
            if score > best_score:
                best_score = score
                best_pt = (x, y)

    return best_pt


def _resolve_emoji_pool(thumbnail_cfg: dict, settings: dict) -> list[Path]:
    """
    Return a list of emoji Paths to draw from.

    Priority:
    1. Explicit ``thumbnail.emoji_overlay.pool`` list in YAML (filenames, with or without extension).
    2. Auto-selected from ``commentary.theme`` / ``channel.niche`` via ``_THEME_EMOJI_POOLS``.
    3. All non-arrow images in the emojis directory.
    """
    import random as _random

    emoji_cfg = thumbnail_cfg.get("emoji_overlay", {})
    all_files = {
        p.stem: p
        for p in _EMOJIS_DIR.iterdir()
        if p.suffix.lower() in (".png", ".webp", ".jpg", ".jpeg")
        and "arrow" not in p.stem.lower()
    } if _EMOJIS_DIR.is_dir() else {}

    if not all_files:
        return []

    # 1. Explicit pool override.
    explicit = emoji_cfg.get("pool") or []
    if explicit:
        resolved = [all_files[Path(name).stem] for name in explicit if Path(name).stem in all_files]
        if resolved:
            return resolved

    # 2. Auto-select by theme / niche keywords.
    theme = (settings.get("commentary", {}).get("theme") or "").lower()
    niche = (settings.get("channel", {}).get("niche") or "").lower()
    for keyword, stems in _THEME_EMOJI_POOLS.items():
        if keyword in theme or keyword in niche:
            resolved = [all_files[s] for s in stems if s in all_files]
            if resolved:
                return resolved

    # 3. Fallback: everything available.
    return list(all_files.values())


def _place_emoji(
    image: Image.Image,
    emoji_path: Path,
    centre: tuple,
    size: int,
) -> None:
    """Composite one emoji image onto *image* at *centre* (in-place)."""
    emoji_img = Image.open(emoji_path).convert("RGBA")
    emoji_img = emoji_img.resize((size, size), Image.Resampling.LANCZOS)
    ex, ey = centre
    paste_x = int(ex - size / 2.0)
    paste_y = int(ey - size / 2.0)
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    layer.paste(emoji_img, (paste_x, paste_y), emoji_img)
    image.paste(Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB"))


def _add_thumbnail_overlays(
    image: Image.Image,
    thumbnail_cfg: dict,
    settings: dict,
) -> None:
    """
    Run YOLO detection and (optionally) composite an arrow and/or emoji onto
    *image* in-place.  Every failure mode is caught and logged so a thumbnail
    is always produced.
    """
    import random as _random

    arrow_cfg = thumbnail_cfg.get("arrow_overlay", {})
    emoji_cfg = thumbnail_cfg.get("emoji_overlay", {})
    want_arrow = arrow_cfg.get("enabled", True)
    want_emoji = emoji_cfg.get("enabled", False)

    if not want_arrow and not want_emoji:
        return

    # --- YOLO detection -------------------------------------------------------
    try:
        model = _load_yolo_model()
    except Exception as exc:
        logger.warning("YOLO unavailable – skipping thumbnail overlays: %s", exc)
        return

    try:
        results = model(image, verbose=False)
    except Exception as exc:
        logger.warning("YOLO inference failed: %s", exc)
        return

    boxes = results[0].boxes
    if not boxes or len(boxes) == 0:
        logger.debug("No objects detected – skipping thumbnail overlays")
        return

    best = max(boxes, key=lambda b: float(b.conf))
    bx1, by1, bx2, by2 = best.xyxy[0].tolist()
    cls_name = results[0].names[int(best.cls)]
    conf = float(best.conf)
    cx = (bx1 + bx2) / 2.0
    cy = (by1 + by2) / 2.0

    start = _choose_arrow_start(cx, cy, image.width, image.height)

    # --- Arrow ----------------------------------------------------------------
    if want_arrow:
        if not _ARROW_PNG_PATH.exists():
            logger.debug("Arrow asset missing at %s", _ARROW_PNG_PATH)
        else:
            try:
                tx, ty = _choose_arrow_target_outside_box(bx1, by1, bx2, by2, cx, cy, start, pad=0)
                tx = max(0, min(image.width - 1, tx))
                ty = max(0, min(image.height - 1, ty))
                arrow_sprite = Image.open(_ARROW_PNG_PATH).convert("RGBA")
                max_len, min_len = _arrow_lengths(image, arrow_cfg)
                _overlay_arrow_png(image, arrow_sprite, start, (tx, ty), (cx, cy), max_len, min_len)
                logger.info(
                    "Arrow overlay: %s (conf=%.2f) obj=(%d,%d) tip=(%d,%d)",
                    cls_name, conf, int(cx), int(cy), tx, ty,
                )
            except Exception as exc:
                logger.warning("Arrow overlay failed: %s", exc)

    # --- Emoji ----------------------------------------------------------------
    if want_emoji:
        try:
            pool = _resolve_emoji_pool(thumbnail_cfg, settings)
            if not pool:
                logger.debug("No emoji assets found – skipping emoji overlay")
            else:
                emoji_size = int(image.width * emoji_cfg.get("size_ratio", 0.18))
                all_boxes_coords = [b.xyxy[0].tolist() for b in boxes]
                pt = _find_empty_space(
                    all_boxes_coords,
                    image.width,
                    image.height,
                    start,
                    item_w=emoji_size,
                    item_h=emoji_size,
                )
                if pt:
                    chosen = _random.choice(pool)
                    _place_emoji(image, chosen, pt, emoji_size)
                    logger.info("Emoji overlay: %s at %s", chosen.name, pt)
                else:
                    logger.debug("No empty space found for emoji")
        except Exception as exc:
            logger.warning("Emoji overlay failed: %s", exc)

DEFAULT_SEARCH_STAGES = [
    ("hot", 200),
    ("top_day", 200),
    ("new", 200),
    ("rising", 200),
]


# ---------------------------------------------------------------------------
# Content filters
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

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


def _is_single_image_post(submission) -> bool:
    """
    Return True only when the Reddit post is a single, native image —
    not a gallery, not a video, not a link/article with a preview image.

    Criteria (ALL must pass):
    - post_hint == "image"  (Reddit's own classification)
    - is_gallery is False   (single image, not a multi-image gallery)
    - URL is i.redd.it hosted OR ends with a known static image extension
    """
    if getattr(submission, "is_gallery", False):
        return False

    post_hint = (getattr(submission, "post_hint", "") or "").lower()
    if post_hint != "image":
        return False

    url = (getattr(submission, "url", "") or "").lower()
    image_ext = any(url.endswith(e) for e in (".jpg", ".jpeg", ".png", ".webp"))
    reddit_hosted = "i.redd.it/" in url
    return image_ext or reddit_hosted


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
    """Return the direct image URL for a verified single-image post."""
    try:
        u = (getattr(submission, "url", "") or "").strip()
        if not u:
            return None
        lu = u.lower()
        if any(lu.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
            return u
        if "i.redd.it/" in lu:
            return u
        # Reddit preview fallback (HTML-entity-decoded)
        prev = getattr(submission, "preview", None)
        if isinstance(prev, dict):
            images = prev.get("images") or []
            if images:
                source = images[0].get("source") or {}
                pu = source.get("url")
                if pu:
                    return html.unescape(str(pu).strip())
        return None
    except Exception:
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
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
        return out
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def source_thumbnail(settings: dict) -> Optional[dict]:
    """
    Search Reddit for a single native image post to use as the YouTube
    thumbnail.  Only accepts posts where Reddit itself classifies the content
    as a single image (post_hint == "image", not a gallery).

    Returns a dict with ``path``, ``url``, and ``submission_id`` on success,
    or None if no suitable image is found.  No video-frame extraction or
    collage fallback is performed.
    """
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
    tolerance = float(cfg.get("aspect_ratio_tolerance", 0.5))
    target_ratio = target_w / target_h
    banned_words = cfg.get("banned_words", [])

    # Word-length heuristics: images that needed a long title or body text to
    # go viral likely did so because of the *story*, not the image itself.
    # Set to 0 to disable a limit.
    max_title_words = int(cfg.get("max_title_words", 10))
    # Any selftext at all suggests the story is carrying the post; cap at a
    # small number so a one-liner context is tolerated but walls of text aren't.
    max_selftext_words = int(cfg.get("max_selftext_words", cfg.get("max_description_words", 20)))
    # If True, reject posts that have *any* non-empty selftext (strictest mode).
    require_no_selftext = bool(cfg.get("require_no_selftext", False))

    import random
    subs = list(subs)
    random.shuffle(subs)

    search_stages = cfg.get("search_stages", DEFAULT_SEARCH_STAGES)

    for stage_name, limit in search_stages:
        for sub in subs:
            subreddit = reddit.subreddit(sub)
            try:
                submissions = fetch_feed(subreddit, stage_name, limit)
                for submission in submissions:
                    if submission.is_self or submission.id in used_ids:
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
                        logger.debug(
                            "Skip %s: title too long (%d words > %d limit)",
                            submission.id,
                            len((submission.title or "").split()),
                            max_title_words,
                        )
                        continue
                    selftext = (getattr(submission, "selftext", "") or "").strip()
                    if require_no_selftext and selftext:
                        logger.debug("Skip %s: has selftext (require_no_selftext=true)", submission.id)
                        continue
                    if max_selftext_words > 0 and selftext and _exceeds_max_words(selftext, max_selftext_words):
                        logger.debug(
                            "Skip %s: selftext too long (%d words > %d limit) — story-driven post",
                            submission.id,
                            len(selftext.split()),
                            max_selftext_words,
                        )
                        continue

                    # Only accept explicit single-image Reddit posts
                    if not _is_single_image_post(submission):
                        logger.debug(
                            "Skip %s: not a single image post (post_hint=%r, is_gallery=%r)",
                            submission.id,
                            getattr(submission, "post_hint", None),
                            getattr(submission, "is_gallery", False),
                        )
                        continue

                    url = _pick_image_url(submission)
                    if not url:
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
                        logger.debug(
                            "Skip %s: image aspect ratio not close enough to %s:%s",
                            submission.id, target_w, target_h,
                        )
                        continue

                    _add_thumbnail_overlays(out, cfg, settings)

                    out_path = THUMBS / f"{submission.id}_yt.jpg"
                    out.save(out_path, "JPEG", quality=90, optimize=True, progressive=True)

                    logger.info(
                        "Thumbnail sourced from r/%s post %s (%s)",
                        sub, submission.id, stage_name,
                    )
                    return {
                        "submission_id": submission.id,
                        "path": str(out_path),
                        "original_path": None,
                        "url": url,
                    }

            except Exception as e:
                logger.warning(
                    "Thumbnail search failed for r/%s (%s): %s", sub, stage_name, e
                )

    logger.warning(
        "No suitable single-image thumbnail found across %d subreddits. "
        "The video will be uploaded without a custom thumbnail.",
        len(subs),
    )
    return None
