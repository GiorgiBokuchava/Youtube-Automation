from __future__ import annotations

import os
import subprocess
from pathlib import Path
import logging

from youtube_automation.media.ffmpeg import ffmpeg_bin as _ffmpeg_bin
from youtube_automation.media.ffprobe_streams import probe_av_stream_durations


def _assert_av_duration_match(path: Path, *, tolerance_sec: float = 0.15) -> None:
    video_dur, audio_dur = probe_av_stream_durations(path)
    if video_dur is None or audio_dur is None:
        raise RuntimeError(f"Could not probe stitched output durations: {path}")
    if abs(video_dur - audio_dur) > tolerance_sec:
        raise RuntimeError(
            f"Stitched output A/V mismatch (freeze risk): video={video_dur:.3f}s "
            f"audio={audio_dur:.3f}s path={path}"
        )


def stitch_clips(*, clip_paths: list[Path], output_path: Path) -> Path:
    if not clip_paths:
        raise ValueError("clip_paths is empty")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(__name__)
    clip_count = len(clip_paths)

    logger.info("🎬 Stitching %d clips → %s", clip_count, output_path)

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

    # Filter concat normalizes SAR/fps per clip. The concat demuxer + CFR can drop
    # video frames when inputs mix sample aspect ratios (common on Reddit clips).
    chains: list[str] = []
    concat_inputs: list[str] = []
    for i in range(clip_count):
        chains.append(
            f"[{i}:v]setpts=PTS-STARTPTS,fps=30,"
            f"scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}]"
        )
        chains.append(
            f"[{i}:a]aresample=48000,asetpts=PTS-STARTPTS[a{i}]"
        )
        concat_inputs.append(f"[v{i}][a{i}]")
    filter_complex = (
        ";".join(chains)
        + ";"
        + "".join(concat_inputs)
        + f"concat=n={clip_count}:v=1:a=1[vout][aout];"
        "[aout]alimiter=limit=0.97[aout_limited]"
    )

    cmd = [
        _ffmpeg_bin(),
        "-hide_banner",
        "-y",
        "-loglevel",
        "info",
        "-stats",
    ]
    for p in clip_paths:
        cmd.extend(["-i", str(p.resolve())])
    cmd.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout_limited]",
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
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )

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

    _assert_av_duration_match(output_path)
    logger.info("✅ Stitching completed successfully")
    return output_path
