import pytest

from youtube_automation.pipeline import (
    InsufficientOutputDurationError,
    InsufficientSourceDurationError,
    run_pipeline,
)


def test_pipeline_aborts_before_upload_when_source_too_short(
    mocker, minimal_settings, dummy_video
):
    settings = {
        **minimal_settings,
        "final_target_duration": 2,
        "post": {
            "enforce_min_source_duration": True,
            "min_source_duration_ratio": 1.0,
        },
    }
    mocker.patch(
        "youtube_automation.pipeline.source_all_videos",
        return_value=[
            {
                "id": "1",
                "title": "short",
                "local_path": str(dummy_video),
                "duration_sec": 30,
            }
        ],
    )
    upload = mocker.patch("youtube_automation.pipeline.upload_video")
    render = mocker.patch("youtube_automation.pipeline.render_clip")

    with pytest.raises(InsufficientSourceDurationError):
        run_pipeline(settings, dry_run=True, cleanup=False)

    upload.assert_not_called()
    render.assert_not_called()
