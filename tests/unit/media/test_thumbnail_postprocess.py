from unittest.mock import patch

from PIL import Image

from youtube_automation.media.thumbnail import _apply_postprocess


def test_postprocess_skipped_when_disabled():
    im = Image.new("RGB", (64, 64), color=(100, 100, 100))
    out = _apply_postprocess(im, {"postprocess": {"enabled": False}})
    assert out is im


def test_postprocess_applies_when_enabled():
    im = Image.new("RGB", (64, 64), color=(100, 100, 100))
    with patch("youtube_automation.media.thumbnail.ImageOps.autocontrast") as ac:
        ac.return_value = im
        with patch("youtube_automation.media.thumbnail.ImageEnhance.Color") as color:
            with patch("youtube_automation.media.thumbnail.ImageEnhance.Contrast") as contrast:
                with patch(
                    "youtube_automation.media.thumbnail.ImageEnhance.Sharpness"
                ) as sharp:
                    color.return_value.enhance.return_value = im
                    contrast.return_value.enhance.return_value = im
                    sharp.return_value.enhance.return_value = im
                    _apply_postprocess(
                        im,
                        {
                            "postprocess": {
                                "enabled": True,
                                "autocontrast_cutoff": 2,
                                "color": 1.1,
                                "contrast": 1.05,
                                "sharpness": 1.2,
                            }
                        },
                    )
    ac.assert_called_once_with(im, cutoff=2)
    color.return_value.enhance.assert_called_once_with(1.1)
    contrast.return_value.enhance.assert_called_once_with(1.05)
    sharp.return_value.enhance.assert_called_once_with(1.2)
