#!/usr/bin/env python3
"""
Full freeze + duration test:
- Uses ALL normalized videos
- Includes commentary where available
- Re-renders clips (no reuse of old rendered files)
- Stitches everything
- Adds background music
- Verifies audio and video durations match
"""

import json
import subprocess
import logging
from pathlib import Path

from youtube_automation.config.loader import load_env, load_settings
from youtube_automation.media.composition import render_clip, stitch_clips
from youtube_automation.media.music import add_background_music

# Paths
BASE = Path("out/animals")
NORMALIZED = BASE / "normalized_videos"
VOICEOVERS = BASE / "voiceovers"
RENDERED = BASE / "rendered_clips"
OUTPUTS = BASE / "outputs"

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger("freeze-test")


def _probe(path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,duration",
        "-of",
        "json",
        str(path),
    ]
    return json.loads(subprocess.check_output(cmd))


def _probe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nk=1:nw=1",
        str(path),
    ]
    return float(subprocess.check_output(cmd).strip())


def main() -> None:
    load_env()
    settings = load_settings("animals")

    if not NORMALIZED.exists():
        raise RuntimeError(f"Missing folder: {NORMALIZED}")

    videos = sorted(NORMALIZED.glob("*.mp4"))
    if not videos:
        raise RuntimeError("No normalized videos found")

    logger.info("Found %d normalized clips", len(videos))

    RENDERED.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    # Clean previous outputs (handle locked files)
    for p in RENDERED.glob("*.mp4"):
        try:
            p.unlink()
        except (PermissionError, OSError):
            pass  # File is locked, skip it
    for p in OUTPUTS.glob("test_*.mp4"):
        try:
            p.unlink()
        except (PermissionError, OSError):
            pass  # File is locked, skip it

    rendered_paths: list[Path] = []
    total_source_duration = 0.0

    for video in videos:
        vid_id = video.stem.replace("normalized_", "")
        commentary = None

        # Commentary audio if exists
        for ext in (".mp3", ".wav"):
            candidate = VOICEOVERS / f"{vid_id}_vo{ext}"
            if candidate.exists():
                commentary = candidate
                break

        out = RENDERED / f"{vid_id}_rendered.mp4"

        logger.info(
            "Rendering %-20s | commentary=%s",
            video.name,
            commentary.name if commentary else "NO",
        )

        orig_vol = settings.get("audio", {}).get("original_clip_volume_db", 0.0)

        render_clip(
            input_video=video,
            output_video=out,
            commentary_audio=commentary,
            commentary_offset_sec=0.45,
            original_volume_db=orig_vol,
            commentary_gain=settings.get("commentary", {}).get("commentary_gain", 1.0),
        )

        dur = _probe_duration(out)
        total_source_duration += dur
        rendered_paths.append(out)

    logger.info(
        "Rendered %d clips | total stitched duration ≈ %.1fs (%.2f min)",
        len(rendered_paths),
        total_source_duration,
        total_source_duration / 60.0,
    )

    # Stitch
    stitched = OUTPUTS / "test_full_raw.mp4"
    stitch_clips(
        clip_paths=rendered_paths,
        output_path=stitched,
    )

    # Add music
    final = OUTPUTS / "test_full_final.mp4"
    final = add_background_music(
        video_path=stitched,
        output_path=final,
        settings=settings,
    )

    # Verify durations
    meta = _probe(final)

    video_dur = None
    audio_dur = None
    for s in meta["streams"]:
        if s["codec_type"] == "video":
            video_dur = float(s["duration"])
        elif s["codec_type"] == "audio":
            audio_dur = float(s["duration"])

    print("\n--- FINAL RESULT ---")
    print(f"Video duration: {video_dur:.3f}s ({video_dur/60:.2f} min)")
    print(f"Audio duration: {audio_dur:.3f}s ({audio_dur/60:.2f} min)")

    if abs(video_dur - audio_dur) > 0.05:
        raise RuntimeError("❌ FREEZE RISK: audio/video duration mismatch")

    if video_dur < 180:
        print("⚠️  WARNING: final video is under 3 minutes")
    else:
        print("✅ Duration >= 3 minutes")

    print("✅ No freeze detected")


if __name__ == "__main__":
    main()
