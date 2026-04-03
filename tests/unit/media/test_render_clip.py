import subprocess
from pathlib import Path

import pytest

from youtube_automation.media.composition.clip import (
    COMMENTARY_HAS_AUDIO,
    COMMENTARY_NO_AUDIO,
    NO_COMMENTARY_HAS_AUDIO,
    NO_COMMENTARY_NO_AUDIO,
    RenderClipError,
    render_clip,
)
from youtube_automation.media.ffprobe_streams import ContainerStreamInfo


@pytest.fixture
def patch_ffmpeg_path(mocker):
    mocker.patch("youtube_automation.media.composition.clip.ensure_ffmpeg", return_value=None)


def _ffmpeg_success(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    out = Path(cmd[-1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"fakevideo")
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def test_render_no_commentary_source_has_audio(mocker, tmp_path, patch_ffmpeg_path):
    inv = tmp_path / "in.mp4"
    outv = tmp_path / "out.mp4"
    inv.write_bytes(b"x")
    mocker.patch(
        "youtube_automation.media.composition.clip.probe_container_streams",
        side_effect=[
            ContainerStreamInfo(has_video=True, has_audio=True),
            ContainerStreamInfo(has_video=True, has_audio=True),
        ],
    )
    mocker.patch(
        "youtube_automation.media.composition.clip.subprocess.run",
        side_effect=_ffmpeg_success,
    )

    r = render_clip(input_video=inv, output_video=outv, commentary_audio=None)
    assert r.output_path == outv
    assert r.path_kind == NO_COMMENTARY_HAS_AUDIO


def test_render_no_commentary_source_no_audio(mocker, tmp_path, patch_ffmpeg_path):
    inv = tmp_path / "in.mp4"
    outv = tmp_path / "out.mp4"
    inv.write_bytes(b"x")
    mocker.patch(
        "youtube_automation.media.composition.clip.probe_container_streams",
        side_effect=[
            ContainerStreamInfo(has_video=True, has_audio=False),
            ContainerStreamInfo(has_video=True, has_audio=True),
        ],
    )
    run = mocker.patch(
        "youtube_automation.media.composition.clip.subprocess.run",
        side_effect=_ffmpeg_success,
    )

    r = render_clip(input_video=inv, output_video=outv, commentary_audio=None)
    assert r.path_kind == NO_COMMENTARY_NO_AUDIO
    cmd = run.call_args[0][0]
    assert "lavfi" in cmd
    assert "anullsrc" in "".join(cmd)


def test_render_commentary_source_has_audio(mocker, tmp_path, patch_ffmpeg_path):
    inv = tmp_path / "in.mp4"
    com = tmp_path / "vo.mp3"
    outv = tmp_path / "out.mp4"
    inv.write_bytes(b"x")
    com.write_bytes(b"x")
    mocker.patch(
        "youtube_automation.media.composition.clip.probe_container_streams",
        side_effect=[
            ContainerStreamInfo(has_video=True, has_audio=True),
            ContainerStreamInfo(has_video=False, has_audio=True),
            ContainerStreamInfo(has_video=True, has_audio=True),
        ],
    )
    mocker.patch(
        "youtube_automation.media.composition.clip.subprocess.run",
        side_effect=_ffmpeg_success,
    )

    r = render_clip(input_video=inv, output_video=outv, commentary_audio=com)
    assert r.path_kind == COMMENTARY_HAS_AUDIO


def test_render_commentary_source_no_audio(mocker, tmp_path, patch_ffmpeg_path):
    inv = tmp_path / "in.mp4"
    com = tmp_path / "vo.mp3"
    outv = tmp_path / "out.mp4"
    inv.write_bytes(b"x")
    com.write_bytes(b"x")
    mocker.patch(
        "youtube_automation.media.composition.clip.probe_container_streams",
        side_effect=[
            ContainerStreamInfo(has_video=True, has_audio=False),
            ContainerStreamInfo(has_video=False, has_audio=True),
            ContainerStreamInfo(has_video=True, has_audio=True),
        ],
    )
    mocker.patch(
        "youtube_automation.media.composition.clip.subprocess.run",
        side_effect=_ffmpeg_success,
    )

    r = render_clip(input_video=inv, output_video=outv, commentary_audio=com)
    assert r.path_kind == COMMENTARY_NO_AUDIO


def test_ffmpeg_failure_includes_stderr(mocker, tmp_path, patch_ffmpeg_path):
    inv = tmp_path / "in.mp4"
    outv = tmp_path / "out.mp4"
    inv.write_bytes(b"x")
    mocker.patch(
        "youtube_automation.media.composition.clip.probe_container_streams",
        side_effect=[
            ContainerStreamInfo(has_video=True, has_audio=True),
        ],
    )

    def fail(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout="",
            stderr="Invalid data found when processing input",
        )

    mocker.patch("youtube_automation.media.composition.clip.subprocess.run", side_effect=fail)

    with pytest.raises(RenderClipError) as excinfo:
        render_clip(input_video=inv, output_video=outv, commentary_audio=None)

    err = excinfo.value
    assert err.returncode == 1
    assert "Invalid data found" in err.stderr
    assert "Invalid data found" in str(err)
    assert "ffmpeg exited" in str(err)


def test_preflight_missing_input(mocker, tmp_path, patch_ffmpeg_path):
    inv = tmp_path / "nope.mp4"
    outv = tmp_path / "out.mp4"
    with pytest.raises(RenderClipError, match="does not exist"):
        render_clip(input_video=inv, output_video=outv, commentary_audio=None)
