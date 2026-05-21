from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from youtube_automation.media.thumbnail import (
    _crop_and_resize,
    _passes_source_quality,
    _pick_image_url,
    _thumbnail_needs_source_detection,
)


def test_pick_image_prefers_largest_preview_resolution():
    s = SimpleNamespace(
        url="https://www.reddit.com/r/foo/comments/bar/title/",
        preview={
            "images": [
                {
                    "resolutions": [
                        {
                            "url": "https://preview.redd.it/small.jpg",
                            "width": 320,
                            "height": 240,
                        },
                        {
                            "url": "https://preview.redd.it/large.jpg",
                            "width": 1080,
                            "height": 720,
                        },
                    ],
                    "source": {
                        "url": "https://preview.redd.it/source.jpg",
                        "width": 640,
                        "height": 480,
                    },
                }
            ]
        },
    )
    u = _pick_image_url(s)
    assert u == "https://preview.redd.it/large.jpg"


def test_pick_image_prefers_source_when_larger_than_resolutions():
    s = SimpleNamespace(
        url="https://www.reddit.com/r/foo/comments/bar/title/",
        preview={
            "images": [
                {
                    "resolutions": [
                        {
                            "url": "https://preview.redd.it/mid.jpg",
                            "width": 640,
                            "height": 480,
                        },
                    ],
                    "source": {
                        "url": "https://preview.redd.it/huge.jpg",
                        "width": 2048,
                        "height": 1536,
                    },
                }
            ]
        },
    )
    assert _pick_image_url(s) == "https://preview.redd.it/huge.jpg"


def test_pick_image_skips_gif_direct_url():
    s = SimpleNamespace(url="https://i.redd.it/abc.gif", preview=None)
    assert _pick_image_url(s) is None


def test_passes_source_quality_rejects_small_dimensions():
    im = Image.new("RGB", (800, 500))
    cfg = {"min_source_width": 900, "min_source_height": 600}
    assert _passes_source_quality(im, cfg) is False


def test_passes_source_quality_rejects_low_pixel_count():
    im = Image.new("RGB", (1000, 500))
    cfg = {"min_source_pixels": 600000}
    assert _passes_source_quality(im, cfg) is False


def test_passes_source_quality_rejects_blurry_when_cv2_available():
    im = Image.new("RGB", (1200, 800), color=(128, 128, 128))
    cfg = {
        "min_source_width": 900,
        "reject_blurry": True,
        "blur_variance_threshold": 80.0,
    }
    with patch(
        "youtube_automation.media.thumbnail._blur_variance",
        return_value=10.0,
    ):
        assert _passes_source_quality(im, cfg) is False


def test_passes_source_quality_accepts_when_blur_check_skipped():
    im = Image.new("RGB", (1200, 800))
    cfg = {
        "min_source_width": 900,
        "reject_blurry": True,
        "blur_variance_threshold": 80.0,
    }
    with patch(
        "youtube_automation.media.thumbnail._blur_variance",
        return_value=None,
    ):
        assert _passes_source_quality(im, cfg) is True


def test_thumbnail_needs_source_detection_only_for_gate_or_subject_crop():
    assert _thumbnail_needs_source_detection({"require_detection": True}) is True
    assert _thumbnail_needs_source_detection({"subject_aware_crop": True}) is True
    assert (
        _thumbnail_needs_source_detection(
            {"arrow_overlay": {"enabled": True, "dynamic_detection": True}}
        )
        is False
    )


def test_crop_and_resize_subject_aware_maps_poi(mocker):
    mocker.patch(
        "youtube_automation.media.thumbnail._is_acceptable_ratio",
        return_value=True,
    )
    im = Image.new("RGB", (1600, 1200))
    out, mapped = _crop_and_resize(
        im,
        1920,
        1080,
        16 / 9,
        0.5,
        crop_point=(800.0, 600.0),
        subject_aware_crop=True,
    )
    assert out is not None
    assert out.size == (1920, 1080)
    assert mapped is not None
    assert 900 <= mapped[0] <= 1020
    assert 500 <= mapped[1] <= 700
