from pathlib import Path
from youtube_automation.media.composition.clip import render_clip


def test_render_clip_without_commentary_uses_copy(mocker, tmp_path):
    input_video = tmp_path / "in.mp4"
    output_video = tmp_path / "out.mp4"
    input_video.write_bytes(b"mp4")

    mocker.patch(
        "youtube_automation.media.composition.clip.subprocess.run",
        return_value=type("P", (), {"returncode": 0, "stderr": ""})(),
    )

    out = render_clip(
        input_video=input_video,
        output_video=output_video,
        commentary_audio=None,
    )

    assert out == output_video


def test_render_clip_with_commentary(mocker, tmp_path):
    input_video = tmp_path / "in.mp4"
    commentary = tmp_path / "vo.mp3"
    output_video = tmp_path / "out.mp4"

    input_video.write_bytes(b"mp4")
    commentary.write_bytes(b"mp3")

    mocker.patch(
        "youtube_automation.media.composition.clip._probe_duration_seconds",
        return_value=1.5,
    )

    mocker.patch(
        "youtube_automation.media.composition.clip.subprocess.run",
        return_value=type("P", (), {"returncode": 0, "stderr": ""})(),
    )

    out = render_clip(
        input_video=input_video,
        output_video=output_video,
        commentary_audio=commentary,
    )

    assert out == output_video
