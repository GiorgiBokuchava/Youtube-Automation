from pathlib import Path

import pytest

from youtube_automation.media.composition.clip import RenderClipResult
from youtube_automation.pipeline import (
    InsufficientOutputDurationError,
    run_pipeline,
)


def test_pipeline_aborts_before_upload_when_rendered_output_too_short(
    mocker, minimal_settings, tmp_path
):
    v1 = tmp_path / "a.mp4"
    v1.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    thumb_path = tmp_path / "thumb.jpg"
    thumb_path.write_bytes(b"x")

    settings = {
        **minimal_settings,
        "final_target_duration": 2,
        "post": {
            "enforce_min_source_duration": True,
            "min_source_duration_ratio": 1.0,
        },
        "commentary": {**minimal_settings["commentary"], "every_nth": 0},
    }

    mocker.patch(
        "youtube_automation.pipeline.source_all_videos",
        return_value=[
            {
                "id": "1",
                "title": "ok",
                "local_path": str(v1),
                "duration_sec": 720,
            }
        ],
    )
    mocker.patch(
        "youtube_automation.pipeline.source_thumbnail",
        return_value={"path": str(thumb_path)},
    )
    mocker.patch(
        "youtube_automation.pipeline.analyze_clip_audio",
        return_value=type(
            "AA",
            (),
            {
                "has_audio": True,
                "mean_volume_db": -20.0,
                "max_volume_db": -1.0,
                "silence_ratio": 0.05,
                "has_sustained_audio": True,
                "music_likely": False,
            },
        )(),
    )

    def render_side_effect(*, output_video, **kwargs):
        output_video.parent.mkdir(parents=True, exist_ok=True)
        output_video.write_bytes(b"ok")
        return RenderClipResult(output_path=output_video, path_kind="test_ok")

    mocker.patch("youtube_automation.pipeline.render_clip", side_effect=render_side_effect)
    mocker.patch(
        "youtube_automation.pipeline.probed_media_duration_seconds",
        return_value=15.0,
    )
    upload = mocker.patch("youtube_automation.pipeline.upload_video")
    stitch = mocker.patch("youtube_automation.pipeline.stitch_clips")

    with pytest.raises(InsufficientOutputDurationError, match="rendered"):
        run_pipeline(settings, dry_run=True, cleanup=False)

    upload.assert_not_called()
    stitch.assert_not_called()
