from pathlib import Path
from unittest.mock import MagicMock

import pytest

from youtube_automation.pipeline import (
    InsufficientOutputDurationError,
    assert_final_output_meets_target,
    assert_rendered_meets_target,
    min_required_source_seconds,
)


def _settings(**overrides):
    base = {
        "final_target_duration": 2,
        "post": {
            "enforce_min_source_duration": True,
            "min_source_duration_ratio": 1.0,
        },
    }
    base.update(overrides)
    return base


def test_assert_rendered_raises_when_probed_total_too_short(mocker):
    mocker.patch(
        "youtube_automation.pipeline.probed_media_duration_seconds",
        side_effect=[15.0, 10.0],
    )
    paths = [Path("a.mp4"), Path("b.mp4")]
    with pytest.raises(InsufficientOutputDurationError, match="rendered"):
        assert_rendered_meets_target(_settings(), paths)


def test_assert_final_output_raises_when_file_too_short(mocker):
    mocker.patch(
        "youtube_automation.pipeline.probed_media_duration_seconds",
        return_value=30.0,
    )
    with pytest.raises(InsufficientOutputDurationError, match="final output"):
        assert_final_output_meets_target(_settings(), Path("out/final.mp4"))


def test_assert_rendered_passes_when_total_meets_target(mocker):
    mocker.patch(
        "youtube_automation.pipeline.probed_media_duration_seconds",
        return_value=60.0,
    )
    assert_rendered_meets_target(_settings(), [Path("a.mp4"), Path("b.mp4")])


def test_min_required_unchanged():
    assert min_required_source_seconds(_settings()) == 120


def test_probed_media_duration_uses_format_fallback(mocker):
    mocker.patch(
        "youtube_automation.pipeline.probe_av_stream_durations",
        return_value=(None, None),
    )
    mocker.patch(
        "youtube_automation.pipeline.probe_audio_duration",
        return_value=125.5,
    )
    from youtube_automation.pipeline import probed_media_duration_seconds

    assert probed_media_duration_seconds(Path("x.mp4")) == 125.5


def test_assert_raises_when_duration_unprobeable(mocker):
    mocker.patch(
        "youtube_automation.pipeline.probed_media_duration_seconds",
        return_value=0.0,
    )
    with pytest.raises(InsufficientOutputDurationError, match="Could not probe"):
        assert_final_output_meets_target(_settings(), Path("out/final.mp4"))
