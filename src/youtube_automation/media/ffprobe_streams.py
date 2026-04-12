"""FFprobe-based detection of video/audio streams in a media file."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.media.ffmpeg import ensure_ffmpeg


@dataclass(frozen=True)
class ContainerStreamInfo:
    has_video: bool
    has_audio: bool


@dataclass(frozen=True)
class VideoStreamSize:
    width: int
    height: int


class StreamProbeError(RuntimeError):
    """ffprobe failed or could not parse output."""


def _ffprobe_bin() -> str:
    ffmpeg_dir = ensure_ffmpeg()
    return "ffprobe" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffprobe")


def probe_container_streams(path: Path) -> ContainerStreamInfo:
    """
    Return whether the container has at least one video and/or audio stream.
    """
    cmd = [
        _ffprobe_bin(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise StreamProbeError(
            f"ffprobe failed (exit {p.returncode}). stderr:\n{p.stderr or ''}"
        )
    try:
        data = json.loads(p.stdout or "{}")
    except json.JSONDecodeError as e:
        raise StreamProbeError(f"ffprobe JSON parse error: {e}") from e

    streams = data.get("streams") or []
    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    return ContainerStreamInfo(has_video=has_video, has_audio=has_audio)


def probe_video_stream_size(path: Path) -> VideoStreamSize | None:
    """
    Return width/height of the first video stream, or None if unavailable.
    """
    cmd = [
        _ffprobe_bin(),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        return None
    try:
        data = json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        return None
    streams = data.get("streams") or []
    if not streams:
        return None
    w = streams[0].get("width")
    h = streams[0].get("height")
    if not w or not h:
        return None
    return VideoStreamSize(width=int(w), height=int(h))
