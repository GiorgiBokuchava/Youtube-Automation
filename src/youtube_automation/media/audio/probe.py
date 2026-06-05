from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from youtube_automation.media.ffmpeg import ensure_ffmpeg
from youtube_automation.media.audio import _ina_detector

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioAnalysis:
    # ── FFmpeg metrics (always collected) ──────────────────────────────────
    has_audio: bool
    mean_volume_db: Optional[float]
    max_volume_db: Optional[float]
    silence_ratio: Optional[float]
    has_sustained_audio: bool

    # ── Final decision ─────────────────────────────────────────────────────
    music_likely: bool

    # ── Extended fields (populated by inaSpeechSegmenter when available) ──
    # Fraction of the clip classified as 'music' by the detector.
    music_ratio: Optional[float] = None
    # Time windows flagged as music: ((start_sec, end_sec), ...).
    music_segments: Optional[tuple[tuple[float, float], ...]] = None
    # Which detector produced the `music_likely` decision.
    # One of: 'ina' | 'ffmpeg' | 'ffmpeg_fallback' | 'none'
    detector_used: str = "none"


_VOL_MEAN_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
_VOL_MAX_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


# ── FFmpeg helpers (kept for debug metrics and legacy fallback) ────────────


def _run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess[str]:
    ffmpeg_dir = ensure_ffmpeg()
    ffmpeg = "ffmpeg" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffmpeg")
    return subprocess.run([ffmpeg, *args], capture_output=True, text=True)


def _probe_duration_seconds(media_path: Path) -> Optional[float]:
    ffmpeg_dir = ensure_ffmpeg()
    ffprobe = "ffprobe" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffprobe")
    p = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(media_path)],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        return None
    try:
        return float(p.stdout.strip())
    except Exception:
        return None


def _detect_volume(video_path: Path) -> tuple[Optional[float], Optional[float]]:
    p = _run_ffmpeg([
        "-hide_banner", "-nostats", "-i", str(video_path),
        "-vn", "-af", "volumedetect", "-f", "null", "-",
    ])
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
    p = _run_ffmpeg([
        "-hide_banner", "-nostats", "-i", str(video_path),
        "-vn", "-af", "silencedetect=n=-35dB:d=0.35", "-f", "null", "-",
    ])
    text = (p.stderr or "") + "\n" + (p.stdout or "")
    silence_total = 0.0
    for line in text.splitlines():
        if "silence_duration:" in line:
            try:
                silence_total += float(line.split("silence_duration:")[1].strip().split()[0])
            except Exception:
                continue
    return max(0.0, min(silence_total, duration)) / duration


def _ffmpeg_music_likely(has_sustained_audio: bool, mean_db: Optional[float]) -> bool:
    """Legacy heuristic: loud sustained audio (no speech/noise discrimination)."""
    return has_sustained_audio and mean_db is not None and mean_db > -28.0


# ── inaSpeechSegmenter path ───────────────────────────────────────────────


def _run_ina_detection(
    video_path: Path, *, vad_engine: str = "smn"
) -> tuple[float, tuple[tuple[float, float], ...]]:
    """Run inaSpeechSegmenter and return *(music_ratio, music_segments)*.

    *music_ratio* is the fraction of the clip classified as ``'music'``.
    *music_segments* is a tuple of ``(start_sec, end_sec)`` pairs for those
    windows (relative to the start of the clip).

    Raises any exception from the segmenter unchanged so the caller can
    decide whether to fall back.
    """
    segmenter = _ina_detector.get_segmenter(vad_engine=vad_engine)
    segmentation = segmenter(str(video_path))  # list of (label, start, stop)

    total = sum(stop - start for _, start, stop in segmentation)
    if total <= 0:
        return 0.0, ()

    music_dur = 0.0
    music_segs: list[tuple[float, float]] = []
    for label, start, stop in segmentation:
        if label == "music":
            music_dur += stop - start
            music_segs.append((float(start), float(stop)))

    return music_dur / total, tuple(music_segs)


# ── Public API ────────────────────────────────────────────────────────────


def analyze_clip_audio(
    video_path: Path, *, settings: dict | None = None
) -> AudioAnalysis:
    """Analyse the audio track of *video_path* and return an ``AudioAnalysis``.

    Parameters
    ----------
    video_path:
        Path to the video (or audio) file to analyse.
    settings:
        The merged channel + base YAML settings dict.  When ``None``, the
        function behaves as if ``audio.music_detection.engine`` is ``"ina"``
        with ``fallback_on_missing: true`` — so existing call-sites that do
        not pass settings continue to work unchanged.

    Detection engine
    ----------------
    Configure ``audio.music_detection`` in any channel or base YAML::

        audio:
          music_detection:
            enabled: true
            engine: ina              # ina | ffmpeg
            vad_engine: smn          # smn (speech/music/noise) | sm (speech/music)
            music_ratio_threshold: 0.3
            fallback_on_missing: true   # ffmpeg heuristic if ina not installed
            fallback_on_error: false    # never mute on detector failure (safe default)

    When ``engine: ina`` and inaSpeechSegmenter is installed the CNN decides
    ``music_likely``.  Loud speech, barking, engine noise, and crowd noise are
    tagged as ``speech`` or ``noise`` rather than ``music`` — eliminating the
    main source of false positives from the old FFmpeg heuristic.

    The FFmpeg volume/silence metrics are always collected and stored in the
    returned ``AudioAnalysis`` regardless of the chosen engine — use them for
    threshold tuning and debugging.
    """
    # ── Always-on FFmpeg metrics ───────────────────────────────────────────
    mean_db, max_db = _detect_volume(video_path)
    silence_ratio = _detect_silence_ratio(video_path)

    has_audio = mean_db is not None and mean_db > -55.0
    has_sustained_audio = (
        has_audio and silence_ratio is not None and silence_ratio < 0.35
    )

    # ── Detection config ───────────────────────────────────────────────────
    det_cfg = (settings or {}).get("audio", {}).get("music_detection", {})
    enabled: bool = bool(det_cfg.get("enabled", True))
    engine: str = str(det_cfg.get("engine", "ina"))
    vad_engine: str = str(det_cfg.get("vad_engine", "smn"))
    ratio_threshold: float = float(det_cfg.get("music_ratio_threshold", 0.3))
    fallback_on_missing: bool = bool(det_cfg.get("fallback_on_missing", True))
    fallback_on_error: bool = bool(det_cfg.get("fallback_on_error", False))

    music_ratio: Optional[float] = None
    music_segments: Optional[tuple[tuple[float, float], ...]] = None
    detector_used = "none"
    music_likely = False

    if not enabled:
        music_likely = _ffmpeg_music_likely(has_sustained_audio, mean_db)
        detector_used = "ffmpeg"

    elif engine == "ina":
        if _ina_detector.is_available():
            try:
                music_ratio, music_segments = _run_ina_detection(
                    video_path, vad_engine=vad_engine
                )
                detector_used = "ina"
                music_likely = music_ratio >= ratio_threshold
                logger.debug(
                    "%s: ina music_ratio=%.3f threshold=%.2f music_likely=%s  segments=%s",
                    video_path.name,
                    music_ratio,
                    ratio_threshold,
                    music_likely,
                    music_segments,
                )
            except Exception as exc:
                logger.warning(
                    "%s: inaSpeechSegmenter raised %s: %s",
                    video_path.name,
                    type(exc).__name__,
                    exc,
                )
                if fallback_on_error:
                    music_likely = _ffmpeg_music_likely(has_sustained_audio, mean_db)
                    detector_used = "ffmpeg_fallback"
                    logger.info(
                        "%s: fell back to ffmpeg heuristic (fallback_on_error=True)",
                        video_path.name,
                    )
                # else: music_likely stays False → never mute on detector failure

        elif fallback_on_missing:
            music_likely = _ffmpeg_music_likely(has_sustained_audio, mean_db)
            detector_used = "ffmpeg_fallback"
            logger.debug(
                "%s: inaSpeechSegmenter not installed — using ffmpeg fallback",
                video_path.name,
            )
        else:
            pass  # ina not installed, fallback disabled → music_likely=False (safe)

    elif engine == "ffmpeg":
        music_likely = _ffmpeg_music_likely(has_sustained_audio, mean_db)
        detector_used = "ffmpeg"

    return AudioAnalysis(
        has_audio=has_audio,
        mean_volume_db=mean_db,
        max_volume_db=max_db,
        silence_ratio=silence_ratio,
        has_sustained_audio=has_sustained_audio,
        music_likely=music_likely,
        music_ratio=music_ratio,
        music_segments=music_segments,
        detector_used=detector_used,
    )
