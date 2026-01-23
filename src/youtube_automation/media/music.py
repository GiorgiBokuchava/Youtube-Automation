from __future__ import annotations

import random
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional

from youtube_automation.config.loader import BASE_DIR
from youtube_automation.media.ffmpeg import ensure_ffmpeg


def _ffmpeg_bin() -> str:
    ffmpeg_dir = ensure_ffmpeg()
    return "ffmpeg" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffmpeg")


def _ffprobe_bin() -> str:
    ffmpeg_dir = ensure_ffmpeg()
    return "ffprobe" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffprobe")


def _probe_duration(path: Path) -> Optional[float]:
    cmd = [
        _ffprobe_bin(),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nk=1:nw=1",
        str(path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return None
    try:
        return float(p.stdout.strip())
    except Exception:
        return None


def _collect_music_tracks(settings: dict) -> List[Path]:
    music_cfg = settings.get("music", {})
    root = BASE_DIR / music_cfg.get("library_root", "")
    if not root.exists():
        return []

    tags = music_cfg.get("tags", [])
    tracks: List[Path] = []

    for tag in tags:
        d = root / tag
        if d.exists():
            tracks.extend(sorted(d.glob("*.mp3")))

    return tracks


def _select_tracks(
    tracks: List[Path], target_duration: float, max_repeats: int
) -> List[Tuple[Path, float]]:
    random.shuffle(tracks)
    selected: List[Tuple[Path, float]] = []
    total = 0.0

    for t in tracks:
        if total >= target_duration:
            break
        dur = _probe_duration(t)
        if not dur:
            continue
        selected.append((t, dur))
        total += dur

    return selected


def _build_music_bed(
    *,
    selected: List[Tuple[Path, float]],
    target_duration: float,
    fade_in: float,
    fade_out: float,
    out_path: Path,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    concat_file = out_path.with_suffix(".txt")
    with open(concat_file, "w") as f:
        for track, _ in selected:
            f.write(f"file '{track.resolve().as_posix()}'\n")

    # IMPORTANT:
    # apad + atrim ensures EXACT duration
    filter_complex = (
        f"[0:a]"
        f"afade=t=in:st=0:d={fade_in},"
        f"afade=t=out:st={target_duration - fade_out}:d={fade_out},"
        f"apad,"
        f"atrim=0:{target_duration}"
        f"[final]"
    )

    cmd = [
        _ffmpeg_bin(),
        "-hide_banner",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-filter_complex",
        filter_complex,
        "-map",
        "[final]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]

    try:
        p = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300
        )
        if p.returncode != 0:
            raise RuntimeError(f"Music bed build failed: {p.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("music bed build timed out")

    return out_path


def _mix_music_into_video(
    *,
    video_path: Path,
    music_path: Path,
    output_path: Path,
    original_duck_db: float,
    music_volume_db: float,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    video_dur = _probe_duration(video_path)
    orig_factor = 10 ** (original_duck_db / 20.0)
    music_factor = 10 ** (music_volume_db / 20.0)

    filter_complex = (
        f"[0:a]volume={orig_factor},apad[a0];"
        f"[1:a]volume={music_factor},apad[a1];"
        f"[a0][a1]amix=inputs=2:duration=longest,"
        f"atrim=0:{video_dur}[aout]"
    )

    cmd = [
        _ffmpeg_bin(),
        "-hide_banner",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(music_path),
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
        str(output_path),
    ]

    try:
        p = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300
        )
        if p.returncode != 0:
            raise RuntimeError(f"Music mix failed: {p.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("music mix timed out")

    return output_path


def add_background_music(
    *, video_path: Path, output_path: Path, settings: dict
) -> Path:
    music_cfg = settings.get("music", {})
    if not music_cfg.get("enabled", False):
        return video_path

    tracks = _collect_music_tracks(settings)
    if not tracks:
        return video_path

    video_dur = _probe_duration(video_path)
    if not video_dur or video_dur <= 1.0:
        return video_path

    selected = _select_tracks(
        tracks,
        video_dur,
        int(music_cfg.get("max_track_repeats", 1)),
    )
    if not selected:
        return video_path

    tmp_music = output_path.with_suffix(".music.m4a")

    _build_music_bed(
        selected=selected,
        target_duration=video_dur,
        fade_in=float(music_cfg.get("fade_in_sec", 0.8)),
        fade_out=float(music_cfg.get("fade_out_sec", 0.8)),
        out_path=tmp_music,
    )

    result = _mix_music_into_video(
        video_path=video_path,
        music_path=tmp_music,
        output_path=output_path,
        original_duck_db=float(music_cfg.get("original_duck_db", -6)),
        music_volume_db=float(music_cfg.get("music_volume_db", -12)),
    )

    tmp_music.unlink(missing_ok=True)
    return result
