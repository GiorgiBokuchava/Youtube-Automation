"""YOLO-based thumbnail arrow: detect a salient object and point the arrow at it."""

from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_PIL_RESAMPLE = getattr(
    getattr(Image, "Resampling", Image),
    "LANCZOS",
    Image.BICUBIC,
)

# COCO class ids (Ultralytics yolov8n.pt)
COCO_PERSON = 0
COCO_BICYCLE = 1
COCO_CAR = 2
COCO_MOTORCYCLE = 3
COCO_BUS = 5
COCO_TRUCK = 7

DEFAULT_DETECT_CLASSES = (
    COCO_PERSON,
    COCO_BICYCLE,
    COCO_CAR,
    COCO_MOTORCYCLE,
    COCO_BUS,
    COCO_TRUCK,
)

_CLASS_WEIGHT: dict[int, float] = {
    COCO_CAR: 1.0,
    COCO_TRUCK: 1.0,
    COCO_BUS: 0.95,
    COCO_MOTORCYCLE: 0.9,
    COCO_PERSON: 0.85,
    COCO_BICYCLE: 0.7,
}

_MODEL_CACHE: dict[str, object] = {}


def _get_yolo(model_name: str):
    if model_name not in _MODEL_CACHE:
        from ultralytics import YOLO

        _MODEL_CACHE[model_name] = YOLO(model_name)
    return _MODEL_CACHE[model_name]


def _parse_detection_cfg(arrow_cfg: dict) -> dict:
    det = arrow_cfg.get("detection") or {}
    if det.get("enabled", True) is False:
        return {"enabled": False}
    raw_classes = det.get("classes", list(DEFAULT_DETECT_CLASSES))
    class_ids = {int(c) for c in raw_classes}
    return {
        "enabled": True,
        "model": str(det.get("model", arrow_cfg.get("model", "yolov8n.pt"))),
        "confidence": float(det.get("confidence", 0.35)),
        "class_ids": class_ids or set(DEFAULT_DETECT_CLASSES),
    }


def _score_box(
    xyxy: tuple[float, float, float, float],
    conf: float,
    cls_id: int,
    img_w: int,
    img_h: int,
) -> float:
    x1, y1, x2, y2 = xyxy
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if area <= 0:
        return 0.0
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    # Prefer subjects not hugging the frame edge (thumbnail crop noise).
    margin_x = img_w * 0.06
    margin_y = img_h * 0.06
    edge_penalty = 1.0
    if cx < margin_x or cx > img_w - margin_x or cy < margin_y or cy > img_h - margin_y:
        edge_penalty = 0.55
    weight = _CLASS_WEIGHT.get(cls_id, 0.75)
    return area * float(conf) * weight * edge_penalty


def detect_point_of_interest(
    image: Image.Image,
    arrow_cfg: dict,
) -> Optional[tuple[float, float]]:
    """
    Return (x, y) image coordinates for the arrow tip to aim at, or None if no detection.
    """
    cfg = _parse_detection_cfg(arrow_cfg)
    if not cfg.get("enabled"):
        return None

    rgb = np.asarray(image.convert("RGB"))
    try:
        model = _get_yolo(cfg["model"])
        results = model.predict(
            source=rgb,
            verbose=False,
            conf=cfg["confidence"],
        )
    except Exception as exc:
        logger.warning("Thumbnail arrow detection failed: %s", exc)
        return None

    if not results:
        return None

    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return None

    img_w, img_h = image.size
    best_score = 0.0
    best_center: Optional[tuple[float, float]] = None
    allowed = cfg["class_ids"]

    for i in range(len(boxes)):
        cls_id = int(boxes.cls[i].item())
        if cls_id not in allowed:
            continue
        xyxy = tuple(float(v) for v in boxes.xyxy[i].tolist())
        conf = float(boxes.conf[i].item())
        score = _score_box(xyxy, conf, cls_id, img_w, img_h)
        if score > best_score:
            best_score = score
            x1, y1, x2, y2 = xyxy
            best_center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    if best_center is None:
        logger.info("Thumbnail arrow: no detections above threshold")
        return None

    logger.info(
        "Thumbnail arrow target at (%.0f, %.0f) score=%.0f",
        best_center[0],
        best_center[1],
        best_score,
    )
    return best_center


def _arrow_tip_local(aw: int, ah: int) -> tuple[float, float]:
    """Tip of arrow-pointing-down asset (bottom center)."""
    return (aw / 2.0, float(ah - 1))


def _rotate_point(
    cx: float, cy: float, x: float, y: float, angle_rad: float
) -> tuple[float, float]:
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    rx, ry = x - cx, y - cy
    return (cx + rx * cos_a - ry * sin_a, cy + rx * sin_a + ry * cos_a)


def compose_arrow_pointing_at(
    arrow_rgba: Image.Image,
    *,
    canvas_w: int,
    canvas_h: int,
    target_xy: tuple[float, float],
    max_width_ratio: float,
    band_h: int,
    margin: int,
    avoid_rect: Optional[tuple[int, int, int, int]] = None,
) -> Optional[tuple[Image.Image, tuple[int, int]]]:
    """
    Scale, rotate, and return (arrow_image, paste_xy) so the tip points at target_xy.

    avoid_rect: optional (x, y, w, h) that arrow must not overlap (e.g. emoji).
    """
    tx, ty = target_xy
    aw, ah = arrow_rgba.size
    if aw < 1 or ah < 1:
        return None

    max_arrow_w = max(1, int(canvas_w * max_width_ratio))
    scale = min(1.0, max_arrow_w / aw, band_h / ah)
    # Arrow PNGs can be large square canvases; allow downscale below legacy 0.52 floor.
    if scale < 0.12:
        return None
    ar = arrow_rgba.resize(
        (max(1, int(aw * scale)), max(1, int(ah * scale))),
        _PIL_RESAMPLE,
    )
    aw, ah = ar.size
    tip_x, tip_y = _arrow_tip_local(aw, ah)
    cx, cy = aw / 2.0, ah / 2.0

    ux = tx - canvas_w / 2.0
    uy = ty - canvas_h / 2.0
    norm = math.hypot(ux, uy)
    if norm < 1.0:
        ux, uy = 0.0, -1.0
        norm = 1.0
    ux /= norm
    uy /= norm

    offset = max(ah * 1.05, min(canvas_w, canvas_h) * 0.10)
    tail_x = tx + ux * offset
    tail_y = ty + uy * offset

    point_angle = math.atan2(ty - tail_y, tx - tail_x)
    rotation_deg = math.degrees(point_angle - math.pi / 2.0)

    rotated = ar.rotate(
        -rotation_deg,
        expand=True,
        resample=Image.Resampling.BICUBIC,
    )
    rot_cx = aw / 2.0
    rot_cy = ah / 2.0
    new_cx, new_cy = rotated.width / 2.0, rotated.height / 2.0
    tip_rot_x, tip_rot_y = _rotate_point(
        rot_cx,
        rot_cy,
        tip_x,
        tip_y,
        math.radians(-rotation_deg),
    )
    tip_rot_x += new_cx - rot_cx
    tip_rot_y += new_cy - rot_cy

    paste_x = int(round(tx - tip_rot_x))
    paste_y = int(round(ty - tip_rot_y))

    rw, rh = rotated.width, rotated.height

    def _fits(px: int, py: int) -> Optional[tuple[int, int]]:
        cx = max(margin, min(px, canvas_w - margin - rw))
        cy = max(margin, min(py, canvas_h - margin - rh))
        if avoid_rect is None:
            return cx, cy
        ax, ay, aw_r, ah_r = avoid_rect
        ar_box = (cx, cy, cx + rw, cy + rh)
        em_box = (ax, ay, ax + aw_r, ay + ah_r)
        if _boxes_overlap(ar_box, em_box):
            return None
        return cx, cy

    candidates = [
        (paste_x, paste_y),
        (paste_x, paste_y + int(rh * 0.35)),
        (paste_x - int(rw * 0.35), paste_y),
        (paste_x, paste_y - int(rh * 0.25)),
        (paste_x - int(rw * 0.55), paste_y + int(rh * 0.2)),
    ]
    for px, py in candidates:
        placed = _fits(px, py)
        if placed:
            return rotated, placed

    return None


def _boxes_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
