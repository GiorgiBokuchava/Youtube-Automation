import subprocess
from pathlib import Path

from youtube_automation.media.composition.timeline import stitch_clips


def test_stitch_clips_writes_concat_file(mocker, tmp_path):
    mocker.patch(
        "youtube_automation.media.composition.timeline.ensure_ffmpeg", return_value=None
    )
    clips = [
        tmp_path / "a.mp4",
        tmp_path / "b.mp4",
    ]

    for c in clips:
        c.write_bytes(b"mp4")

    out = tmp_path / "final.mp4"

    mocker.patch(
        "youtube_automation.media.composition.timeline.subprocess.run",
        return_value=subprocess.CompletedProcess(["ffmpeg"], 0, stdout="", stderr=""),
    )

    stitched = stitch_clips(clip_paths=clips, output_path=out)

    assert stitched == out

    concat_file = tmp_path / "final_concat.txt"
    text = concat_file.read_text()

    assert "file" in text
    assert "a.mp4" in text
    assert "b.mp4" in text


def test_stitch_clips_uses_fps_mode_not_vsync(mocker, tmp_path):
    mocker.patch(
        "youtube_automation.media.composition.timeline.ensure_ffmpeg", return_value=None
    )
    clips = [tmp_path / "a.mp4"]
    clips[0].write_bytes(b"mp4")
    out = tmp_path / "final.mp4"

    captured: list[list[str]] = []

    def capture_run(cmd, **kwargs):
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    mocker.patch(
        "youtube_automation.media.composition.timeline.subprocess.run",
        side_effect=capture_run,
    )

    stitch_clips(clip_paths=clips, output_path=out)

    assert captured, "ffmpeg should have been invoked"
    flat = captured[0]
    assert "-fps_mode" in flat
    assert "cfr" in flat
    assert "-vsync" not in flat
