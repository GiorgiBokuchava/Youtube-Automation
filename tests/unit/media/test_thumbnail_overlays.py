from youtube_automation.media.thumbnail import tl_tr_horizontal_room


def test_tl_tr_horizontal_room_wide_canvas():
    assert tl_tr_horizontal_room(1920, 40, 16, 200, 200)


def test_tl_tr_horizontal_room_too_narrow():
    assert not tl_tr_horizontal_room(400, 40, 16, 200, 250)
