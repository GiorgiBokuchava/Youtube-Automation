from unittest.mock import MagicMock

import numpy as np
from PIL import Image

from youtube_automation.media.thumbnail_arrow import (
    compose_arrow_pointing_at,
    detect_point_of_interest,
)


def _fake_box(cls_id: int, xyxy: tuple[float, float, float, float], conf: float):
    box = MagicMock()
    box.cls = [MagicMock(item=lambda: cls_id)]
    box.conf = [MagicMock(item=lambda: conf)]
    box.xyxy = [MagicMock(tolist=lambda: list(xyxy))]
    return box


def test_detect_point_of_interest_picks_best_vehicle(mocker):
    b_car = _fake_box(2, (100, 100, 200, 200), 0.9)
    b_person = _fake_box(0, (10, 10, 30, 30), 0.95)
    boxes = MagicMock()
    boxes.__len__ = lambda self: 2
    boxes.cls = [b_car.cls[0], b_person.cls[0]]
    boxes.conf = [b_car.conf[0], b_person.conf[0]]
    boxes.xyxy = [b_car.xyxy[0], b_person.xyxy[0]]

    result = MagicMock()
    result.boxes = boxes
    model = MagicMock()
    model.predict.return_value = [result]
    mocker.patch(
        "youtube_automation.media.thumbnail_arrow._get_yolo",
        return_value=model,
    )

    img = Image.new("RGB", (400, 300), color=(128, 128, 128))
    pt = detect_point_of_interest(img, {"detection": {"confidence": 0.3}})

    assert pt is not None
    assert 140 <= pt[0] <= 160
    assert 140 <= pt[1] <= 160


def test_compose_arrow_pointing_at_returns_paste_position():
    arrow = Image.new("RGBA", (40, 80), (255, 0, 0, 255))
    out = compose_arrow_pointing_at(
        arrow,
        canvas_w=640,
        canvas_h=360,
        target_xy=(320, 200),
        max_width_ratio=0.2,
        band_h=120,
        margin=16,
    )
    assert out is not None
    rotated, (px, py) = out
    assert rotated.width > 0
    assert 0 <= px < 640
    assert 0 <= py < 360


def test_compose_arrow_avoids_emoji_rect():
    arrow = Image.new("RGBA", (40, 80), (255, 0, 0, 255))
    out = compose_arrow_pointing_at(
        arrow,
        canvas_w=640,
        canvas_h=360,
        target_xy=(600, 30),
        max_width_ratio=0.25,
        band_h=120,
        margin=16,
        avoid_rect=(500, 10, 120, 120),
    )
    assert out is None
