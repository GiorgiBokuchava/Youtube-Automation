"""Scale + pad to 9:16 without cropping (letterbox / pillarbox as needed)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from youtube_automation.media.ffmpeg import ensure_ffmpeg
from youtube_automation.media.ffprobe_streams import probe_container_streams


def _ffmpeg_bin() -> str:
    ffmpeg_dir = ensure_ffmpeg()
    return "ffmpeg" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffmpeg")


def fit_video_to_portrait_box(
    input_path: Path,
    output_path: Path,
    *,
    target_w: int = 1080,
    target_h: int = 1920,
    max_duration_sec: float | None = None,
) -> Path:
    """
    Fit video inside target_w x target_h preserving aspect ratio, pad with black.
    Optionally trims from the start to max_duration_sec (re-encodes for accurate trim).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    info = probe_container_streams(input_path)
    cmd: list[str | Path] = [
        _ffmpeg_bin(),
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
    ]
    if not info.has_audio:
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
            ]
        )

    cmd.extend(
        [
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-r",
            "30",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if max_duration_sec is not None and max_duration_sec > 0:
        cmd.extend(["-t", str(max_duration_sec)])

    if info.has_audio:
        cmd.extend(
            [
                "-af",
                "dynaudnorm=f=200:g=13,volume=1.12,alimiter=limit=0.96",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ar",
                "48000",
            ]
        )
    else:
        cmd.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                "1:a",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
            ]
        )

    cmd.extend(["-movflags", "+faststart", str(output_path)])
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
    return output_path
