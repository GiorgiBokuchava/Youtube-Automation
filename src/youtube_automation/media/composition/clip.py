from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from youtube_automation.media.ffmpeg import ensure_ffmpeg


def _ffmpeg_bin() -> str:
    ffmpeg_dir = ensure_ffmpeg()
    return "ffmpeg" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffmpeg")


def _ffprobe_bin() -> str:
    ffmpeg_dir = ensure_ffmpeg()
    return "ffprobe" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffprobe")


def _probe_duration_seconds(media_path: Path) -> Optional[float]:
    cmd = [
        _ffprobe_bin(),
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


def render_clip(
    *,
    input_video: Path,
    output_video: Path,
    commentary_audio: Optional[Path] = None,
    commentary_offset_sec: float = 0.45,
    ducking_db: float = -12.0,
) -> Path:
    output_video.parent.mkdir(parents=True, exist_ok=True)

    if not commentary_audio or not commentary_audio.exists():
        cmd = [
            _ffmpeg_bin(),
            "-hide_banner",
            "-y",
            "-i",
            str(input_video),
            "-c",
            "copy",
            str(output_video),
        ]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"ffmpeg copy failed: {p.stderr}")
        return output_video

    com_dur = _probe_duration_seconds(commentary_audio)
    if not com_dur:
        com_dur = 2.0

    start = max(0.0, commentary_offset_sec)
    end = start + max(0.1, com_dur)

    duck_factor = 10 ** (ducking_db / 20.0)

    delay_ms = int(start * 1000)

    filter_complex = (
        f"[0:a]volume=enable='between(t,{start:.3f},{end:.3f})':volume={duck_factor:.6f}"
        f"[a0];"
        f"[1:a]adelay={delay_ms}|{delay_ms},volume=1.0[a1];"
        f"[a0][a1]amix=inputs=2:normalize=0:dropout_transition=0[aout]"
    )

    cmd = [
        _ffmpeg_bin(),
        "-hide_banner",
        "-y",
        "-i",
        str(input_video),
        "-i",
        str(commentary_audio),
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_video),
    ]

    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg mix failed: {p.stderr}")

    return output_video
