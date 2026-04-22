import json
import subprocess
from pathlib import Path

import pytest

from youtube_automation.media.ffprobe_streams import (
    ContainerStreamInfo,
    StreamProbeError,
    probe_container_streams,
)


def test_probe_container_streams_parses_json(mocker, tmp_path):
    mocker.patch("youtube_automation.media.ffprobe_streams.ensure_ffmpeg", return_value=None)
    p = tmp_path / "f.mp4"
    p.write_bytes(b"x")

    payload = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264"},
            {"codec_type": "audio", "codec_name": "aac"},
        ]
    }

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(payload), stderr=""
        )

    mocker.patch(
        "youtube_automation.media.ffprobe_streams.subprocess.run",
        side_effect=fake_run,
    )

    info = probe_container_streams(p)
    assert info == ContainerStreamInfo(has_video=True, has_audio=True)


def test_probe_ffprobe_failure(mocker, tmp_path):
    mocker.patch("youtube_automation.media.ffprobe_streams.ensure_ffmpeg", return_value=None)
    p = tmp_path / "f.mp4"
    p.write_bytes(b"x")

    mocker.patch(
        "youtube_automation.media.ffprobe_streams.subprocess.run",
        return_value=subprocess.CompletedProcess(
            ["ffprobe"], 1, stdout="", stderr="not a media file"
        ),
    )

    with pytest.raises(StreamProbeError, match="ffprobe failed"):
        probe_container_streams(p)
