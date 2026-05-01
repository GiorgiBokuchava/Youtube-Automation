from youtube_automation.media.thumbnail import _pick_overlay_rect, _rect_overlap


def test_pick_overlay_rect_avoids_major_object_and_occupied():
    blocked = [(0, 0, 260, 260)]  # force top-left to be unusable
    occupied = [(1920 - 220 - 24, 24, 1920 - 24, 24 + 180)]  # top-right occupied
    rect = _pick_overlay_rect(
        canvas_w=1920,
        canvas_h=1080,
        overlay_w=220,
        overlay_h=180,
        blocked=blocked,
        occupied=occupied,
        margin=24,
    )
    assert rect is not None
    assert not _rect_overlap(rect, blocked[0], pad=12)
    assert not _rect_overlap(rect, occupied[0], pad=12)


def test_pick_overlay_rect_returns_none_when_no_safe_space():
    blocked = [(0, 0, 1920, 1080)]
    rect = _pick_overlay_rect(
        canvas_w=1920,
        canvas_h=1080,
        overlay_w=200,
        overlay_h=200,
        blocked=blocked,
        occupied=[],
        margin=20,
    )
    assert rect is None
