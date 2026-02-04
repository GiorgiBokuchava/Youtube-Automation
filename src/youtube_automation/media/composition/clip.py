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
    original_volume_db: float = 0.0,
    commentary_gain: float = 1.0,
) -> Path:
    output_video.parent.mkdir(parents=True, exist_ok=True)

    if not commentary_audio or not commentary_audio.exists():
        orig_factor = 10 ** (original_volume_db / 20.0)
        print(
            f"[render_clip] no-commentary original_volume_db={original_volume_db}, factor={orig_factor}"
        )

        filter_complex = (
            f"[0:a]" f"volume={orig_factor}," f"aresample=48000,asetpts=N/SR/TB[aout]"
        )

        cmd = [
            _ffmpeg_bin(),
            "-hide_banner",
            "-y",
            "-i",
            str(input_video),
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-r",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            str(output_video),
        ]
        try:
            p = subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300
            )
            if p.returncode != 0:
                raise RuntimeError(f"ffmpeg mix (no commentary) failed: {p.stderr}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("ffmpeg mix (no commentary) timed out")
        return output_video

    com_dur = _probe_duration_seconds(commentary_audio)
    if not com_dur:
        com_dur = 2.0

    video_dur = _probe_duration_seconds(input_video)
    if not video_dur:
        video_dur = 99999.0  # fallback, but usually ffprobe works

    start = max(0.0, commentary_offset_sec)
    end = start + max(0.1, com_dur)

    orig_factor = 10 ** (original_volume_db / 20.0)
    print(
        f"[render_clip] with-commentary original_volume_db={original_volume_db}, factor={orig_factor}"
    )
    delay_ms = int(max(0.0, commentary_offset_sec) * 1000)

    # Base audio: duck only during commentary window, then trim to video length
    # Commentary: delay, boost, trim to video length
    # Mix, then trim again for safety
    filter_complex = (
        f"[0:a]"
        f"volume={orig_factor},"
        f"aresample=48000,asetpts=N/SR/TB[a0];"
        f"[1:a]"
        f"adelay={delay_ms}|{delay_ms},"
        f"volume={commentary_gain},"
        f"aresample=48000,asetpts=N/SR/TB[a1];"
        f"[a0][a1]"
        f"amix=inputs=2:weights=1 4:duration=shortest:dropout_transition=0[aout]"
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
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-r",
        "30",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        # "-shortest",
        str(output_video),
    ]

    try:
        p = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300
        )
        if p.returncode != 0:
            raise RuntimeError(f"ffmpeg mix failed: {p.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg mix timed out")

    return output_video
