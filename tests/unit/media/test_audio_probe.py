"""Tests for media/audio/probe.py — covers both ina and ffmpeg detection paths."""
from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.media.audio import ina_reset
from youtube_automation.media.audio.probe import (
    AudioAnalysis,
    _ffmpeg_music_likely,
    analyze_clip_audio,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(engine="ina", **overrides):
    """Build a minimal settings dict for a given engine."""
    cfg = {
        "enabled": True,
        "engine": engine,
        "vad_engine": "smn",
        "music_ratio_threshold": 0.3,
        "fallback_on_missing": True,
        "fallback_on_error": False,
    }
    cfg.update(overrides)
    return {"audio": {"music_detection": cfg}}


def _patch_ffmpeg(mocker, *, mean=-22.0, max_db=-1.0, silence=0.05):
    mocker.patch(
        "youtube_automation.media.audio.probe._detect_volume",
        return_value=(mean, max_db),
    )
    mocker.patch(
        "youtube_automation.media.audio.probe._detect_silence_ratio",
        return_value=silence,
    )


def _fake_video(tmp_path) -> Path:
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"fake")
    return p


# ---------------------------------------------------------------------------
# Legacy FFmpeg heuristic (unit)
# ---------------------------------------------------------------------------

def test_ffmpeg_music_likely_true():
    assert _ffmpeg_music_likely(True, -22.0) is True


def test_ffmpeg_music_likely_false_quiet():
    assert _ffmpeg_music_likely(True, -40.0) is False


def test_ffmpeg_music_likely_false_no_sustained():
    assert _ffmpeg_music_likely(False, -22.0) is False


# ---------------------------------------------------------------------------
# engine: ffmpeg (explicit)
# ---------------------------------------------------------------------------

def test_ffmpeg_engine_music_likely(mocker, tmp_path):
    _patch_ffmpeg(mocker, mean=-22.0, silence=0.05)

    result = analyze_clip_audio(_fake_video(tmp_path), settings=_settings(engine="ffmpeg"))

    assert result.music_likely is True
    assert result.detector_used == "ffmpeg"
    assert result.music_ratio is None
    assert result.music_segments is None


def test_ffmpeg_engine_not_music_likely_loud_silence(mocker, tmp_path):
    _patch_ffmpeg(mocker, mean=-22.0, silence=0.8)  # silence_ratio 0.8 > 0.35 → not sustained

    result = analyze_clip_audio(_fake_video(tmp_path), settings=_settings(engine="ffmpeg"))

    assert result.music_likely is False
    assert result.detector_used == "ffmpeg"


def test_disabled_falls_back_to_ffmpeg(mocker, tmp_path):
    """enabled: false uses the legacy FFmpeg heuristic."""
    _patch_ffmpeg(mocker, mean=-22.0, silence=0.05)

    result = analyze_clip_audio(
        _fake_video(tmp_path),
        settings=_settings(engine="ina", enabled=False),
    )

    assert result.music_likely is True
    assert result.detector_used == "ffmpeg"


# ---------------------------------------------------------------------------
# engine: ina — ina available, detection succeeds
# ---------------------------------------------------------------------------

def test_ina_music_detected(mocker, tmp_path):
    ina_reset()
    _patch_ffmpeg(mocker)

    mocker.patch(
        "youtube_automation.media.audio.probe._ina_detector.is_available",
        return_value=True,
    )
    mocker.patch(
        "youtube_automation.media.audio.probe._run_ina_detection",
        return_value=(0.55, ((0.0, 6.0), (10.0, 15.0))),
    )

    result = analyze_clip_audio(_fake_video(tmp_path), settings=_settings(engine="ina"))

    assert result.music_likely is True
    assert result.music_ratio == pytest.approx(0.55)
    assert result.music_segments == ((0.0, 6.0), (10.0, 15.0))
    assert result.detector_used == "ina"


def test_ina_no_music(mocker, tmp_path):
    ina_reset()
    _patch_ffmpeg(mocker)

    mocker.patch(
        "youtube_automation.media.audio.probe._ina_detector.is_available",
        return_value=True,
    )
    mocker.patch(
        "youtube_automation.media.audio.probe._run_ina_detection",
        return_value=(0.05, ()),  # only 5 % music — below 0.3 threshold
    )

    result = analyze_clip_audio(_fake_video(tmp_path), settings=_settings(engine="ina"))

    assert result.music_likely is False
    assert result.music_ratio == pytest.approx(0.05)
    assert result.detector_used == "ina"


def test_ina_ratio_threshold_configurable(mocker, tmp_path):
    ina_reset()
    _patch_ffmpeg(mocker)

    mocker.patch(
        "youtube_automation.media.audio.probe._ina_detector.is_available",
        return_value=True,
    )
    mocker.patch(
        "youtube_automation.media.audio.probe._run_ina_detection",
        return_value=(0.25, ((0.0, 3.0),)),
    )

    # Default threshold 0.3 → not flagged
    r1 = analyze_clip_audio(_fake_video(tmp_path), settings=_settings(engine="ina"))
    assert r1.music_likely is False

    # Lower threshold 0.2 → flagged
    r2 = analyze_clip_audio(
        _fake_video(tmp_path),
        settings=_settings(engine="ina", music_ratio_threshold=0.2),
    )
    assert r2.music_likely is True


# ---------------------------------------------------------------------------
# engine: ina — ina not installed
# ---------------------------------------------------------------------------

def test_ina_not_installed_fallback_on(mocker, tmp_path):
    """inaSpeechSegmenter absent + fallback_on_missing=true → ffmpeg heuristic."""
    ina_reset()
    _patch_ffmpeg(mocker, mean=-22.0, silence=0.05)

    mocker.patch(
        "youtube_automation.media.audio.probe._ina_detector.is_available",
        return_value=False,
    )

    result = analyze_clip_audio(
        _fake_video(tmp_path),
        settings=_settings(engine="ina", fallback_on_missing=True),
    )

    assert result.music_likely is True
    assert result.detector_used == "ffmpeg_fallback"
    assert result.music_ratio is None


def test_ina_not_installed_fallback_off(mocker, tmp_path):
    """inaSpeechSegmenter absent + fallback_on_missing=false → never mute."""
    ina_reset()
    _patch_ffmpeg(mocker, mean=-22.0, silence=0.05)

    mocker.patch(
        "youtube_automation.media.audio.probe._ina_detector.is_available",
        return_value=False,
    )

    result = analyze_clip_audio(
        _fake_video(tmp_path),
        settings=_settings(engine="ina", fallback_on_missing=False),
    )

    assert result.music_likely is False
    assert result.detector_used == "none"


# ---------------------------------------------------------------------------
# engine: ina — ina raises
# ---------------------------------------------------------------------------

def test_ina_error_fallback_off_does_not_mute(mocker, tmp_path):
    """Detector error + fallback_on_error=false → safe: music_likely=False."""
    ina_reset()
    _patch_ffmpeg(mocker, mean=-22.0, silence=0.05)

    mocker.patch(
        "youtube_automation.media.audio.probe._ina_detector.is_available",
        return_value=True,
    )
    mocker.patch(
        "youtube_automation.media.audio.probe._run_ina_detection",
        side_effect=RuntimeError("model exploded"),
    )

    result = analyze_clip_audio(
        _fake_video(tmp_path),
        settings=_settings(engine="ina", fallback_on_error=False),
    )

    assert result.music_likely is False
    assert result.detector_used == "none"


def test_ina_error_fallback_on_uses_ffmpeg(mocker, tmp_path):
    """Detector error + fallback_on_error=true → uses ffmpeg heuristic."""
    ina_reset()
    _patch_ffmpeg(mocker, mean=-22.0, silence=0.05)

    mocker.patch(
        "youtube_automation.media.audio.probe._ina_detector.is_available",
        return_value=True,
    )
    mocker.patch(
        "youtube_automation.media.audio.probe._run_ina_detection",
        side_effect=RuntimeError("model exploded"),
    )

    result = analyze_clip_audio(
        _fake_video(tmp_path),
        settings=_settings(engine="ina", fallback_on_error=True),
    )

    assert result.music_likely is True   # loud + sustained → ffmpeg says yes
    assert result.detector_used == "ffmpeg_fallback"


# ---------------------------------------------------------------------------
# No settings (backward compat) — falls back to ffmpeg when ina missing
# ---------------------------------------------------------------------------

def test_no_settings_uses_ffmpeg_fallback(mocker, tmp_path):
    """analyze_clip_audio(path) with no settings must still work."""
    ina_reset()
    _patch_ffmpeg(mocker, mean=-22.0, silence=0.05)

    mocker.patch(
        "youtube_automation.media.audio.probe._ina_detector.is_available",
        return_value=False,
    )

    result = analyze_clip_audio(_fake_video(tmp_path))

    assert result.has_audio is True
    assert result.has_sustained_audio is True
    assert result.music_likely is True
    assert result.detector_used == "ffmpeg_fallback"


# ---------------------------------------------------------------------------
# AudioAnalysis field completeness
# ---------------------------------------------------------------------------

def test_audio_analysis_has_all_fields(mocker, tmp_path):
    ina_reset()
    _patch_ffmpeg(mocker, mean=-22.0, max_db=-1.0, silence=0.05)

    mocker.patch(
        "youtube_automation.media.audio.probe._ina_detector.is_available",
        return_value=True,
    )
    mocker.patch(
        "youtube_automation.media.audio.probe._run_ina_detection",
        return_value=(0.4, ((0.0, 4.0),)),
    )

    aa = analyze_clip_audio(_fake_video(tmp_path), settings=_settings())

    assert isinstance(aa, AudioAnalysis)
    assert aa.has_audio is True
    assert aa.mean_volume_db == pytest.approx(-22.0)
    assert aa.max_volume_db == pytest.approx(-1.0)
    assert aa.silence_ratio == pytest.approx(0.05)
    assert aa.has_sustained_audio is True
    assert aa.music_likely is True
    assert aa.music_ratio == pytest.approx(0.4)
    assert aa.music_segments == ((0.0, 4.0),)
    assert aa.detector_used == "ina"
