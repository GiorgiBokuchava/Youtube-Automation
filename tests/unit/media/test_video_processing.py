import subprocess

from youtube_automation.media.video_processing import normalize_video_aspect_ratio


def test_normalize_returns_original_on_failure(mocker, tmp_path):
    mocker.patch(
        "youtube_automation.media.video_processing.ensure_ffmpeg", return_value=None
    )
    mocker.patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="error"),
    )

    fake = tmp_path / "bad.mp4"
    fake.write_bytes(b"x")

    out = normalize_video_aspect_ratio(
        fake,
        tmp_path / "out.mp4",
        1920,
        1080,
    )

    assert out == fake
