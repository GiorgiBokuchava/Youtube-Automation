from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from youtube_automation.media.ffmpeg import ensure_ffmpeg


@dataclass(frozen=True)
class AudioAnalysis:
    has_audio: bool
    mean_volume_db: Optional[float]
    max_volume_db: Optional[float]
    silence_ratio: Optional[float]
    has_sustained_audio: bool
    music_likely: bool


_VOL_MEAN_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
_VOL_MAX_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def _run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess[str]:
    ffmpeg_dir = ensure_ffmpeg()
    ffmpeg = "ffmpeg" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffmpeg")

    cmd = [ffmpeg, *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def _probe_duration_seconds(media_path: Path) -> Optional[float]:
    ffmpeg_dir = ensure_ffmpeg()
    ffprobe = "ffprobe" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffprobe")

    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nk=1:nw=1",
        str(media_path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return None

    try:
        return float(p.stdout.strip())
    except Exception:
        return None


def _detect_volume(video_path: Path) -> tuple[Optional[float], Optional[float]]:
    p = _run_ffmpeg(
        [
            "-hide_banner",
            "-nostats",
            "-i",
            str(video_path),
            "-vn",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ]
    )

    out = (p.stderr or "") + "\n" + (p.stdout or "")
    mean_m = _VOL_MEAN_RE.search(out)
    max_m = _VOL_MAX_RE.search(out)

    mean_db = float(mean_m.group(1)) if mean_m else None
    max_db = float(max_m.group(1)) if max_m else None
    return mean_db, max_db


def _detect_silence_ratio(video_path: Path) -> Optional[float]:
    duration = _probe_duration_seconds(video_path)
    if not duration or duration <= 0:
        return None

    p = _run_ffmpeg(
        [
            "-hide_banner",
            "-nostats",
            "-i",
            str(video_path),
            "-vn",
            "-af",
            "silencedetect=n=-35dB:d=0.35",
            "-f",
            "null",
            "-",
        ]
    )

    text = (p.stderr or "") + "\n" + (p.stdout or "")

    silence_total = 0.0
    for line in text.splitlines():
        if "silence_duration:" in line:
            try:
                part = line.split("silence_duration:")[1].strip()
                z = float(part.split()[0])
                silence_total += z
            except Exception:
                continue

    silence_total = max(0.0, min(silence_total, duration))
    return silence_total / duration


def analyze_clip_audio(video_path: Path) -> AudioAnalysis:
    mean_db, max_db = _detect_volume(video_path)
    silence_ratio = _detect_silence_ratio(video_path)

    has_audio = mean_db is not None and mean_db > -55.0

    has_sustained_audio = (
        has_audio and silence_ratio is not None and silence_ratio < 0.35
    )

    music_likely = has_sustained_audio and mean_db is not None and mean_db > -28.0

    return AudioAnalysis(
        has_audio=has_audio,
        mean_volume_db=mean_db,
        max_volume_db=max_db,
        silence_ratio=silence_ratio,
        has_sustained_audio=has_sustained_audio,
        music_likely=music_likely,
    )
