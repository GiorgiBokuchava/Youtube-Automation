from pathlib import Path

from youtube_automation.pipeline import run_pipeline


def test_pipeline_end_to_end(mocker, minimal_settings, dummy_video, tmp_path):
    mocker.patch(
        "youtube_automation.media.video.source_videos",
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

    mocker.patch("youtube_automation.media.thumbnail.source_thumbnail", return_value={})

    mocker.patch(
        "youtube_automation.ai.text.commentary.generate_commentary_video_first",
        return_value="funny dog",
    )

    mocker.patch(
        "youtube_automation.ai.tts.service.tts_service.synthesize",
        return_value=type(
            "A", (), {"data": b"x", "ext": ".mp3", "provider": "edge", "model": "edge"}
        )(),
    )

    mocker.patch(
        "youtube_automation.media.audio.probe.analyze_clip_audio",
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
        "youtube_automation.media.composition.clip.render_clip",
        return_value=rendered,
    )

    final = tmp_path / "final.mp4"
    final.write_bytes(b"mp4")

    mocker.patch(
        "youtube_automation.media.composition.timeline.stitch_clips",
        return_value=final,
    )

    session = run_pipeline(minimal_settings)

    assert session["num_clips"] == 1
    assert "voiceover_path" in session["clips"][0]
    assert "rendered_path" in session["clips"][0]
    assert session["output_path"]
