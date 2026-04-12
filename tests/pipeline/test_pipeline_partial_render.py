"""Partial render failure: one clip fails; others stitch; errors are structured."""

from pathlib import Path

import pytest

from youtube_automation.media.composition.clip import RenderClipResult, RenderClipError
from youtube_automation.pipeline import run_pipeline


def test_partial_render_failure_still_stitches_and_records_errors(
    mocker, minimal_settings, tmp_path
):
    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    v1.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    v2.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    thumb_path = tmp_path / "thumb.jpg"
    thumb_path.write_bytes(b"x")

    mocker.patch(
        "youtube_automation.pipeline.source_videos",
        return_value=[
            {
                "id": "1",
                "title": "a",
                "selftext": "",
                "top_comments": [],
                "local_path": str(v1),
                "duration_sec": 5,
            },
            {
                "id": "2",
                "title": "b",
                "selftext": "",
                "top_comments": [],
                "local_path": str(v2),
                "duration_sec": 5,
            },
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

    final = tmp_path / "final.mp4"
    final.write_bytes(b"x")

    def render_side_effect(
        *,
        input_video,
        output_video,
        commentary_audio=None,
        clip_id=None,
        **kwargs,
    ):
        if clip_id == "2":
            raise RenderClipError(
                "ffmpeg failed",
                command=["ffmpeg", "-y", "-i", "in"],
                returncode=42,
                stderr="detailed stderr from ffmpeg",
                stdout="",
                stage="ffmpeg",
            )
        output_video.parent.mkdir(parents=True, exist_ok=True)
        output_video.write_bytes(b"ok")
        return RenderClipResult(output_path=output_video, path_kind="test_ok")

    mocker.patch("youtube_automation.pipeline.render_clip", side_effect=render_side_effect)

    stitch_mock = mocker.patch(
        "youtube_automation.pipeline.stitch_clips",
        return_value=final,
    )
    mocker.patch("youtube_automation.pipeline.add_background_music", return_value=final)
    mocker.patch("youtube_automation.pipeline.save_session")

    settings = {
        **minimal_settings,
        # Skip commentary/TTS so both clips are rendered without voiceovers.
        "commentary": {**minimal_settings["commentary"], "every_nth": 0},
    }
    session = run_pipeline(settings, dry_run=True, cleanup=False)

    stitch_mock.assert_called_once()
    paths = stitch_mock.call_args.kwargs["clip_paths"]
    assert len(paths) == 1
    assert paths[0].name.endswith("1_rendered.mp4")

    errs = session.get("pipeline_errors") or []
    assert len(errs) == 1
    e = errs[0]
    assert e["step"] == "render_clip"
    assert e["clip_id"] == "2"
    assert e["ffmpeg_returncode"] == 42
    assert e["ffmpeg_stderr"] == "detailed stderr from ffmpeg"
    assert "local_path" in e
    assert "output_path" in e
    assert e["commentary_present"] is False
