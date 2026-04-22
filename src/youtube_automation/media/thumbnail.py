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
from PIL import Image, ImageDraw, ImageFilter

from youtube_automation.reddit.client import create_reddit_client
from youtube_automation.storage.sessions import (
    get_used_thumbnail_ids,
    save_session,
    new_session,
)
from youtube_automation.utils.paths import THUMBS


logger = logging.getLogger(__name__)

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


def _find_edge_components(mask: list[list[int]], min_pixels: int) -> list[tuple[int, int, int, int, int]]:
    h = len(mask)
    w = len(mask[0]) if h else 0
    if w == 0 or h == 0:
        return []

    seen = [[False] * w for _ in range(h)]
    out: list[tuple[int, int, int, int, int]] = []
    dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))

    for y in range(h):
        row = mask[y]
        for x in range(w):
            if row[x] == 0 or seen[y][x]:
                continue
            stack = [(x, y)]
            seen[y][x] = True
            min_x = max_x = x
            min_y = max_y = y
            area = 0
            while stack:
                cx, cy = stack.pop()
                area += 1
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)
                for dx, dy in dirs:
                    nx = cx + dx
                    ny = cy + dy
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and mask[ny][nx] == 1:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            if area >= min_pixels:
                out.append((min_x, min_y, max_x + 1, max_y + 1, area))
    return out


def _detect_object_candidates(im: Image.Image, max_candidates: int = 12) -> list[tuple[int, int, int, int]]:
    # Fast, dependency-free objectness proxy: connected components over edge map.
    probe_w = 320
    scale = probe_w / float(im.width)
    probe_h = max(1, int(im.height * scale))
    probe = im.resize((probe_w, probe_h), _PIL_RESAMPLE).convert("L")
    edge = probe.filter(ImageFilter.FIND_EDGES)
    values = list(edge.getdata())
    if not values:
        return []

    mean_edge = sum(values) / len(values)
    threshold = int(max(22, min(95, mean_edge * 1.15)))
    mask: list[list[int]] = []
    i = 0
    for _ in range(probe_h):
        row = [1 if values[i + x] >= threshold else 0 for x in range(probe_w)]
        i += probe_w
        mask.append(row)

    components = _find_edge_components(mask, min_pixels=max(40, (probe_w * probe_h) // 1200))
    if not components:
        return []

    inv_scale_x = im.width / float(probe_w)
    inv_scale_y = im.height / float(probe_h)
    image_area = im.width * im.height

    candidates: list[tuple[int, int, int, int, float]] = []
    for min_x, min_y, max_x, max_y, _ in components:
        x0 = int(min_x * inv_scale_x)
        y0 = int(min_y * inv_scale_y)
        x1 = int(max_x * inv_scale_x)
        y1 = int(max_y * inv_scale_y)
        bw = max(1, x1 - x0)
        bh = max(1, y1 - y0)
        box_area = bw * bh
        area_ratio = box_area / float(image_area)
        if area_ratio < 0.005 or area_ratio > 0.55:
            continue
        candidates.append((x0, y0, x1, y1, area_ratio))

    # Prefer medium-small objects first; huge scene-filling boxes are poor arrow targets.
    candidates.sort(key=lambda b: abs(b[4] - 0.07))
    return [(x0, y0, x1, y1) for x0, y0, x1, y1, _ in candidates[:max_candidates]]


def _arrow_geometry_for_box(
    *,
    box: tuple[int, int, int, int],
    width: int,
    height: int,
    margin: int,
    arrow_len: int,
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2

    # Try placements around the object; only accept fully in-frame arrows.
    options = [
        ((x0 - arrow_len, cy), (x0 + 6, cy)),  # left -> object
        ((x1 + arrow_len, cy), (x1 - 6, cy)),  # right -> object
        ((cx, y0 - arrow_len), (cx, y0 + 6)),  # top -> object
        ((cx, y1 + arrow_len), (cx, y1 - 6)),  # bottom -> object
    ]
    for start, end in options:
        sx, sy = start
        ex, ey = end
        if (
            margin <= sx < width - margin
            and margin <= sy < height - margin
            and margin <= ex < width - margin
            and margin <= ey < height - margin
        ):
            return start, end
    return None


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    thickness: int,
    head_len: int,
) -> None:
    sx, sy = start
    ex, ey = end
    draw.line([start, end], fill=(255, 255, 255), width=thickness + 4)
    draw.line([start, end], fill=(255, 32, 32), width=thickness)

    if abs(ex - sx) >= abs(ey - sy):
        # Horizontal arrow.
        sign = 1 if ex >= sx else -1
        p1 = (ex, ey)
        p2 = (ex - sign * head_len, ey - head_len // 2)
        p3 = (ex - sign * head_len, ey + head_len // 2)
    else:
        # Vertical arrow.
        sign = 1 if ey >= sy else -1
        p1 = (ex, ey)
        p2 = (ex - head_len // 2, ey - sign * head_len)
        p3 = (ex + head_len // 2, ey - sign * head_len)

    draw.polygon([p1, p2, p3], fill=(255, 255, 255))
    inner = (
        p1,
        (
            int((p1[0] + p2[0]) / 2),
            int((p1[1] + p2[1]) / 2),
        ),
        (
            int((p1[0] + p3[0]) / 2),
            int((p1[1] + p3[1]) / 2),
        ),
    )
    draw.polygon(inner, fill=(255, 32, 32))


def _maybe_add_arrow_overlay(im: Image.Image, thumb_cfg: dict) -> Image.Image:
    arrow_cfg = thumb_cfg.get("arrow_overlay", {})
    if not arrow_cfg.get("enabled", False):
        return im

    candidates = _detect_object_candidates(im)
    if not candidates:
        logger.info("Arrow overlay skipped: no suitable object candidates.")
        return im

    w, h = im.size
    margin = max(10, int(min(w, h) * 0.025))
    arrow_len = max(70, int(min(w, h) * 0.14))
    thickness = max(6, int(min(w, h) * 0.009))
    head_len = max(16, int(arrow_len * 0.28))

    chosen: tuple[tuple[int, int], tuple[int, int]] | None = None
    for box in candidates:
        geom = _arrow_geometry_for_box(
            box=box,
            width=w,
            height=h,
            margin=margin,
            arrow_len=arrow_len,
        )
        if geom is not None:
            chosen = geom
            break

    if chosen is None:
        logger.info("Arrow overlay skipped: no placement kept fully visible.")
        return im

    out = im.copy()
    draw = ImageDraw.Draw(out)
    _draw_arrow(draw, chosen[0], chosen[1], thickness=thickness, head_len=head_len)
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

                    out = _maybe_add_arrow_overlay(out, cfg)

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
