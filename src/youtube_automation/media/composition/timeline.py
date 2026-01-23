from __future__ import annotations

import subprocess
from pathlib import Path
import logging

from youtube_automation.media.ffmpeg import ensure_ffmpeg


def _ffmpeg_bin() -> str:
    ffmpeg_dir = ensure_ffmpeg()
    return "ffmpeg" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffmpeg")


def stitch_clips(*, clip_paths: list[Path], output_path: Path) -> Path:
    if not clip_paths:
        raise ValueError("clip_paths is empty")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(__name__)
    logger.info("🎬 Stitching %d clips → %s", len(clip_paths), output_path)

    list_file = output_path.parent / f"{output_path.stem}_concat.txt"
    list_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in clip_paths) + "\n",
        encoding="utf-8",
    )

    cmd = [
        _ffmpeg_bin(),
        "-hide_banner",
        "-y",
        "-fflags",
        "+genpts",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        # Force stable timing
        "-vsync",
        "cfr",
        "-r",
        "30",
        # Re-encode video & audio (prevents drift / weird seek behavior)
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-af",
        "aresample=async=1:first_pts=0",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=300,
        )
        if p.returncode != 0:
            logger.error("FFmpeg concat failed")
            raise RuntimeError("ffmpeg concat failed")
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg concat timed out")
        raise RuntimeError("ffmpeg concat timed out")
    return output_path
