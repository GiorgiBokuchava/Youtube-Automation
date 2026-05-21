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


def probe_av_stream_durations(path: Path) -> tuple[float | None, float | None]:
    """Return (video_duration_sec, audio_duration_sec) for the first of each stream."""
    cmd = [
        _ffprobe_bin(),
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,duration",
        "-of",
        "json",
        str(path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        return None, None
    try:
        data = json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        return None, None
    video_dur: float | None = None
    audio_dur: float | None = None
    for stream in data.get("streams") or []:
        if stream.get("codec_type") == "video" and video_dur is None:
            try:
                video_dur = float(stream["duration"])
            except (KeyError, TypeError, ValueError):
                pass
        elif stream.get("codec_type") == "audio" and audio_dur is None:
            try:
                audio_dur = float(stream["duration"])
            except (KeyError, TypeError, ValueError):
                pass
    return video_dur, audio_dur


def probe_audio_duration(path: Path) -> float:
    """Return the duration of a media file in seconds, or 0.0 on failure."""
    cmd = [
        _ffprobe_bin(),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nk=1:nw=1",
        str(path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        return 0.0
    try:
        return float(p.stdout.strip())
    except Exception:
        return 0.0


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
