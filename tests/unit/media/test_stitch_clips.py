import subprocess
from pathlib import Path

from youtube_automation.media.composition.timeline import stitch_clips


def test_stitch_clips_builds_filter_concat(mocker, tmp_path):
    mocker.patch(
        "youtube_automation.media.composition.timeline._ffmpeg_bin", return_value="ffmpeg"
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
    mocker.patch(
        "youtube_automation.media.composition.timeline.probe_av_stream_durations",
        return_value=(120.0, 120.0),
    )

    stitched = stitch_clips(clip_paths=clips, output_path=out)

    assert stitched == out
    concat_file = tmp_path / "final_concat.txt"
    assert not concat_file.exists()


def test_stitch_clips_uses_filter_concat_not_demuxer_cfr(mocker, tmp_path):
    mocker.patch(
        "youtube_automation.media.composition.timeline._ffmpeg_bin", return_value="ffmpeg"
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
    mocker.patch(
        "youtube_automation.media.composition.timeline.probe_av_stream_durations",
        return_value=(10.0, 10.0),
    )

    stitch_clips(clip_paths=clips, output_path=out)

    assert captured, "ffmpeg should have been invoked"
    flat = " ".join(captured[0])
    assert "-filter_complex" in flat
    assert "concat=n=1:v=1:a=1" in flat
    assert "setsar=1" in flat
    assert "-f concat" not in flat
    assert "-fps_mode" not in flat
