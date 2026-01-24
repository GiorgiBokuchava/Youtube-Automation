from __future__ import annotations

import os
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
    clip_count = len(clip_paths)

    logger.info("🎬 Stitching %d clips → %s", clip_count, output_path)

    # Build concat file
    list_file = output_path.parent / f"{output_path.stem}_concat.txt"
    list_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in clip_paths) + "\n",
        encoding="utf-8",
    )

    base_timeout = int(os.getenv("FFMPEG_BASE_TIMEOUT", "1800"))
    per_clip_timeout = int(os.getenv("FFMPEG_PER_CLIP_TIMEOUT", "30"))
    timeout = base_timeout + clip_count * per_clip_timeout

    preset = os.getenv("FFMPEG_PRESET", "veryfast")
    crf = os.getenv("FFMPEG_CRF", "20")

    logger.info(
        "FFmpeg timeout=%ss preset=%s crf=%s",
        timeout,
        preset,
        crf,
    )

    cmd = [
        _ffmpeg_bin(),
        "-hide_banner",
        "-y",
        # Show progress in CI logs
        "-loglevel",
        "info",
        "-stats",
        # Concat demuxer
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
        # Re-encode (safe, drift-free)
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        preset,
        "-crf",
        str(crf),
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
        subprocess.run(
            cmd,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.error(
            "FFmpeg concat timed out after %ss (%d clips)",
            timeout,
            clip_count,
        )
        raise RuntimeError("ffmpeg concat timed out")
    except subprocess.CalledProcessError as e:
        logger.error("FFmpeg concat failed with return code %s", e.returncode)
        raise RuntimeError("ffmpeg concat failed")

    logger.info("✅ Stitching completed successfully")
    return output_path
