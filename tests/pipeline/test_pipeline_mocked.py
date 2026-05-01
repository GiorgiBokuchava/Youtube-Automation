from pathlib import Path

import pytest

from youtube_automation.media.composition import RenderClipResult
from youtube_automation.pipeline import run_pipeline


def test_pipeline_end_to_end(mocker, minimal_settings, dummy_video, tmp_path):
    thumb_path = tmp_path / "thumb.jpg"
    thumb_path.write_bytes(b"x")

    mocker.patch(
        "youtube_automation.pipeline.source_videos",
        return_value=[
            {
                "id": "1",
                "title": "dog",
                "selftext": "",
                "top_comments": [],
                "local_path": str(dummy_video),
                "duration_sec": 5,
            }
        ],
    )

    mocker.patch(
        "youtube_automation.pipeline.source_thumbnail",
        return_value={"path": str(thumb_path)},
    )

    mocker.patch(
        "youtube_automation.ai.text.commentary.generate_commentary_video_first",
        return_value=("funny dog", "test-model", False),
    )

    mock_tts = mocker.patch("youtube_automation.ai.tts.service.tts_service")
    mock_tts.synthesize.return_value = type(
        "A", (), {"data": b"x", "ext": ".mp3", "provider": "edge", "model": "edge"}
    )()

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
                "music_likely": True,
            },
        )(),
    )

    rendered = tmp_path / "rendered.mp4"
    rendered.write_bytes(b"mp4")

    mocker.patch(
        "youtube_automation.pipeline.render_clip",
        return_value=RenderClipResult(output_path=rendered, path_kind="mock"),
    )

    final = tmp_path / "final.mp4"
    final.write_bytes(b"mp4")

    mocker.patch(
        "youtube_automation.pipeline.stitch_clips",
        return_value=final,
    )

    mocker.patch(
        "youtube_automation.pipeline.add_background_music",
        return_value=final,
    )
    mocker.patch(
        "youtube_automation.pipeline.probe_media_duration_seconds",
        return_value=1.0,
    )

    mocker.patch("youtube_automation.pipeline.save_session")

    session = run_pipeline(minimal_settings, dry_run=True, cleanup=False)

    assert session["num_clips"] == 1
    assert "voiceover_path" in session["clips"][0]
    assert "rendered_path" in session["clips"][0]
    assert session["output_path"]
    assert session.get("pipeline_errors") == []


def test_cleanup_runs_only_when_requested(mocker, minimal_settings, dummy_video, tmp_path):
    thumb_path = tmp_path / "thumb.jpg"
    thumb_path.write_bytes(b"x")

    mocker.patch(
        "youtube_automation.pipeline.source_videos",
        return_value=[
            {
                "id": "1",
                "title": "x",
                "selftext": "",
                "top_comments": [],
                "local_path": str(dummy_video),
                "duration_sec": 5,
            }
        ],
    )
    mocker.patch(
        "youtube_automation.pipeline.source_thumbnail",
        return_value={"path": str(thumb_path)},
    )
    mocker.patch(
        "youtube_automation.ai.text.commentary.generate_commentary_video_first",
        return_value=("c", "m", False),
    )
    mock_tts = mocker.patch("youtube_automation.ai.tts.service.tts_service")
    mock_tts.synthesize.return_value = type(
        "A", (), {"data": b"x", "ext": ".mp3", "provider": "edge", "model": "edge"}
    )()
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
    rendered = tmp_path / "r.mp4"
    rendered.write_bytes(b"x")
    final = tmp_path / "f.mp4"
    final.write_bytes(b"x")
    mocker.patch(
        "youtube_automation.pipeline.render_clip",
        return_value=RenderClipResult(output_path=rendered, path_kind="mock"),
    )
    mocker.patch("youtube_automation.pipeline.stitch_clips", return_value=final)
    mocker.patch("youtube_automation.pipeline.add_background_music", return_value=final)
    mocker.patch(
        "youtube_automation.pipeline.probe_media_duration_seconds",
        return_value=1.0,
    )
    mocker.patch("youtube_automation.pipeline.save_session")

    spy = mocker.patch("youtube_automation.pipeline._cleanup_generated_files")

    run_pipeline(minimal_settings, dry_run=True, cleanup=False)
    spy.assert_not_called()

    run_pipeline(minimal_settings, dry_run=True, cleanup=True)
    assert spy.call_count == 1


def test_cleanup_skipped_when_pipeline_aborts(mocker, minimal_settings):
    mocker.patch("youtube_automation.pipeline.source_videos", return_value=[])
    spy = mocker.patch("youtube_automation.pipeline._cleanup_generated_files")

    with pytest.raises(ValueError, match="No clips"):
        run_pipeline(minimal_settings, dry_run=True, cleanup=True)

    spy.assert_not_called()


def test_pipeline_fails_if_final_video_shorter_than_target(
    mocker, minimal_settings, dummy_video, tmp_path
):
    thumb_path = tmp_path / "thumb.jpg"
    thumb_path.write_bytes(b"x")

    mocker.patch(
        "youtube_automation.pipeline.source_videos",
        return_value=[
            {
                "id": "1",
                "title": "dog",
                "selftext": "",
                "top_comments": [],
                "local_path": str(dummy_video),
                "duration_sec": 5,
            }
        ],
    )
    mocker.patch(
        "youtube_automation.pipeline.source_thumbnail",
        return_value={"path": str(thumb_path)},
    )
    mocker.patch(
        "youtube_automation.ai.text.commentary.generate_commentary_video_first",
        return_value=("funny dog", "test-model", False),
    )
    mock_tts = mocker.patch("youtube_automation.ai.tts.service.tts_service")
    mock_tts.synthesize.return_value = type(
        "A", (), {"data": b"x", "ext": ".mp3", "provider": "edge", "model": "edge"}
    )()
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
                "music_likely": True,
            },
        )(),
    )
    rendered = tmp_path / "rendered.mp4"
    rendered.write_bytes(b"mp4")
    final = tmp_path / "final.mp4"
    final.write_bytes(b"mp4")
    mocker.patch(
        "youtube_automation.pipeline.render_clip",
        return_value=RenderClipResult(output_path=rendered, path_kind="mock"),
    )
    mocker.patch("youtube_automation.pipeline.stitch_clips", return_value=final)
    mocker.patch("youtube_automation.pipeline.add_background_music", return_value=final)
    mocker.patch(
        "youtube_automation.pipeline.probe_media_duration_seconds",
        return_value=30.0,
    )
    mocker.patch("youtube_automation.pipeline.save_session")

    settings = {**minimal_settings, "final_target_duration": 1}
    with pytest.raises(ValueError, match="shorter than required target duration"):
        run_pipeline(settings, dry_run=True, cleanup=False)
