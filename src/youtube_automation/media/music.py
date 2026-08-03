from __future__ import annotations

import os
import random
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from youtube_automation.config.loader import BASE_DIR
from youtube_automation.media.ffmpeg import ffmpeg_bin as _ffmpeg_bin, ffprobe_bin as _ffprobe_bin


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

    # Shuffle the tag order so no single folder is always favoured first.
    shuffled_tags = list(tags)
    random.shuffle(shuffled_tags)
    for tag in shuffled_tags:
        d = root / tag
        if d.exists():
            tag_tracks = list(d.glob("*.mp3"))
            random.shuffle(tag_tracks)
            tracks.extend(tag_tracks)

    return tracks


def _select_tracks(
    tracks: List[Path], target_duration: float, max_repeats: int
) -> List[Tuple[Path, float]]:
    # Pre-probe all tracks once so we don't re-probe on every repeat pass.
    probed: List[Tuple[Path, float]] = []
    for t in tracks:
        dur = _probe_duration(t)
        if dur and dur > 0:
            probed.append((t, dur))

    if not probed:
        return []

    selected: List[Tuple[Path, float]] = []
    total = 0.0

    # Loop up to max_repeats passes; re-shuffle each pass for variety.
    for _ in range(max(1, max_repeats)):
        if total >= target_duration:
            break
        pass_order = probed.copy()
        random.shuffle(pass_order)
        for t, dur in pass_order:
            if total >= target_duration:
                break
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
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=600
        )
        if p.returncode != 0:
            raise RuntimeError(f"Music bed build failed:\n{p.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("music bed build timed out")

    return out_path


def _build_music_volume_filter(
    music_factor: float,
    audible_segments: Optional[List[Tuple[float, float, float]]],
) -> str:
    """Return the FFmpeg audio filter string for the music track.

    *audible_segments* is a list of ``(start_sec, end_sec, factor)`` triples.
    Each segment plays at its own linear volume *factor*; outside all segments
    the track is silenced.  A nested ``if()`` expression evaluated per-frame
    selects the right level without any extra re-encode pass.

    When *audible_segments* is None the music plays at a constant *music_factor*
    across the entire video (shorts / legacy uniform-bed mode).
    """
    if audible_segments is None:
        return f"volume={music_factor:.6f}"

    # Build a nested if() chain from inside out so the first matching segment
    # wins (segments are non-overlapping by construction).
    expr = "0"
    for s, e, f in reversed(audible_segments):
        expr = f"if(gt(between(t,{s:.3f},{e:.3f}),0),{f:.6f},{expr})"
    return f"volume=volume='{expr}':eval=frame"


def _mix_music_into_video(
    *,
    video_path: Path,
    music_path: Path,
    output_path: Path,
    original_duck_db: float,
    music_volume_db: float,
    audible_segments: Optional[List[Tuple[float, float, float]]] = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    video_dur = _probe_duration(video_path)
    if not video_dur or video_dur <= 0:
        raise RuntimeError(f"Could not probe duration of {video_path}")
    music_factor = 10 ** (music_volume_db / 20.0)

    music_vol_filter = _build_music_volume_filter(music_factor, audible_segments)

    # In targeted-replacement mode (audible_segments provided), music_likely clips were
    # already muted at render time — their windows are already silent in the stitched
    # video.  Applying original_duck_db globally would incorrectly reduce the volume of
    # every non-music clip.  Only apply ducking in uniform-bed mode (audible_segments=None)
    # where music and original audio coexist throughout the whole video.
    if audible_segments is not None:
        orig_vol_filter = "volume=1.0"
    else:
        orig_factor = 10 ** (original_duck_db / 20.0)
        orig_vol_filter = f"volume={orig_factor:.6f}"

    filter_complex = (
        f"[0:a]{orig_vol_filter},apad[a0];"
        f"[1:a]{music_vol_filter},apad[a1];"
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
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=600
        )
        if p.returncode != 0:
            raise RuntimeError(f"Music mix failed:\n{p.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("music mix timed out")

    return output_path


def _passthrough(video_path: Path, output_path: Path) -> Path:
    """Return output_path, creating it as a hard link (or copy) of video_path when needed."""
    if video_path.resolve() == output_path.resolve():
        return output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    try:
        os.link(video_path, output_path)
    except OSError:
        shutil.copy2(video_path, output_path)
    return output_path


def add_background_music(
    *,
    video_path: Path,
    output_path: Path,
    settings: dict,
    music_audible_segments: Optional[List[Tuple[float, float, float]]] = None,
) -> Path:
    """Mix a safe-music bed into *video_path* and write the result to *output_path*.

    *music_audible_segments* controls when the music bed is heard and at what level:

    * ``None``  — legacy / shorts behaviour: music plays at a constant
      ``music_volume_db`` level across the entire video.
    * ``[]``    — empty list: no segment needs music; the video is passed through
      unchanged even when ``music.enabled`` is True.
    * non-empty list of ``(start_sec, end_sec, factor)`` triples — music is
      audible only within each window at the per-segment linear *factor* level.
      Outside all segments the track is silenced.  Factors are computed by the
      pipeline and may differ per clip (adaptive volume levelling).
    """
    music_cfg = settings.get("music", {})
    if not music_cfg.get("enabled", False):
        return _passthrough(video_path, output_path)

    # Segments were explicitly computed but no music_likely clips exist — skip.
    if music_audible_segments is not None and len(music_audible_segments) == 0:
        return _passthrough(video_path, output_path)

    tracks = _collect_music_tracks(settings)
    if not tracks:
        return _passthrough(video_path, output_path)

    video_dur = _probe_duration(video_path)
    if not video_dur or video_dur <= 1.0:
        return _passthrough(video_path, output_path)

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
        audible_segments=music_audible_segments,
    )

    tmp_music.unlink(missing_ok=True)
    return result
