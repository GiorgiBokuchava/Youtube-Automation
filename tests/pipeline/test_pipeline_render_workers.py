"""Tests for bounded parallel rendering: worker count resolution and pipeline behaviour."""
from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.media.composition.clip import RenderClipError, RenderClipResult
from youtube_automation.pipeline import _resolve_render_workers, run_pipeline


# ---------------------------------------------------------------------------
# _resolve_render_workers — unit tests
# ---------------------------------------------------------------------------


def test_resolve_render_workers_default():
    """No env var and no config key → safe default of 1."""
    assert _resolve_render_workers({}) == 1


def test_resolve_render_workers_env_override(monkeypatch):
    """RENDER_WORKERS env var is used when it is a valid positive integer."""
    monkeypatch.setenv("RENDER_WORKERS", "2")
    assert _resolve_render_workers({}) == 2


def test_resolve_render_workers_config_override():
    """settings.performance.render_workers is used when env var is absent."""
    settings = {"performance": {"render_workers": 3}}
    assert _resolve_render_workers(settings) == 3


def test_resolve_render_workers_env_takes_precedence_over_config(monkeypatch):
    """RENDER_WORKERS overrides settings.performance.render_workers."""
    monkeypatch.setenv("RENDER_WORKERS", "4")
    settings = {"performance": {"render_workers": 2}}
    assert _resolve_render_workers(settings) == 4


def test_resolve_render_workers_invalid_env_falls_back_to_config(monkeypatch):
    """A non-integer RENDER_WORKERS is ignored; config value is used instead."""
    monkeypatch.setenv("RENDER_WORKERS", "not_a_number")
    settings = {"performance": {"render_workers": 2}}
    assert _resolve_render_workers(settings) == 2


def test_resolve_render_workers_zero_env_falls_back_to_default(monkeypatch):
    """RENDER_WORKERS=0 is not a valid positive integer; falls back to 1."""
    monkeypatch.setenv("RENDER_WORKERS", "0")
    assert _resolve_render_workers({}) == 1


def test_resolve_render_workers_zero_config_falls_back_to_default():
    """A config value of 0 is not a valid positive integer; falls back to 1."""
    settings = {"performance": {"render_workers": 0}}
    assert _resolve_render_workers(settings) == 1


def test_resolve_render_workers_invalid_config_falls_back_to_default():
    """A non-integer config value is ignored; falls back to 1."""
    settings = {"performance": {"render_workers": "bad"}}
    assert _resolve_render_workers(settings) == 1


# ---------------------------------------------------------------------------
# Helpers shared by pipeline integration tests
# ---------------------------------------------------------------------------


def _make_clips(tmp_path: Path, count: int = 3) -> list[dict]:
    clips = []
    for i in range(1, count + 1):
        p = tmp_path / f"clip{i}.mp4"
        p.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        clips.append(
            {
                "id": str(i),
                "title": f"clip {i}",
                "selftext": "",
                "top_comments": [],
                "local_path": str(p),
                "duration_sec": 5,
            }
        )
    return clips


def _patch_common(mocker, tmp_path: Path, clips: list[dict], render_side_effect):
    """Patch all pipeline dependencies and return the stitch_clips mock."""
    thumb_path = tmp_path / "thumb.jpg"
    thumb_path.write_bytes(b"x")
    final = tmp_path / "final.mp4"
    final.write_bytes(b"x")

    mocker.patch("youtube_automation.pipeline.source_all_videos", return_value=clips)
    mocker.patch(
        "youtube_automation.pipeline.source_thumbnail",
        return_value={"path": str(thumb_path)},
    )
    mocker.patch(
        "youtube_automation.pipeline.analyze_clip_audio",
        return_value=type(
            "AA",
            (),
            {
                "has_audio": True,
                "mean_volume_db": -20.0,
                "max_volume_db": -1.0,
                "silence_ratio": 0.05,
                "has_sustained_audio": True,
                "music_likely": False,
            },
        )(),
    )
    mocker.patch("youtube_automation.pipeline.render_clip", side_effect=render_side_effect)
    stitch_mock = mocker.patch(
        "youtube_automation.pipeline.stitch_clips", return_value=final
    )
    mocker.patch("youtube_automation.pipeline.add_background_music", return_value=final)
    mocker.patch("youtube_automation.pipeline.save_session")
    return stitch_mock


def _no_commentary_settings(minimal_settings: dict) -> dict:
    return {
        **minimal_settings,
        "commentary": {**minimal_settings["commentary"], "every_nth": 0},
    }


def _ok_render(*, input_video, output_video, clip_id=None, **kwargs):
    output_video.parent.mkdir(parents=True, exist_ok=True)
    output_video.write_bytes(b"ok")
    return RenderClipResult(output_path=output_video, path_kind="test")


# ---------------------------------------------------------------------------
# Pipeline integration tests
# ---------------------------------------------------------------------------


def test_render_order_preserved_single_worker(mocker, minimal_settings, tmp_path):
    """With 1 worker (default), rendered paths reach stitch_clips in clip order."""
    clips = _make_clips(tmp_path, count=3)
    settings = _no_commentary_settings(minimal_settings)
    stitch_mock = _patch_common(mocker, tmp_path, clips, _ok_render)

    run_pipeline(settings, dry_run=True)

    paths = stitch_mock.call_args.kwargs["clip_paths"]
    assert [p.name for p in paths] == [
        "1_rendered.mp4",
        "2_rendered.mp4",
        "3_rendered.mp4",
    ]


def test_render_order_preserved_with_two_workers(
    mocker, minimal_settings, tmp_path, monkeypatch
):
    """With RENDER_WORKERS=2 the rendered paths still reach stitch_clips in clip order."""
    monkeypatch.setenv("RENDER_WORKERS", "2")
    clips = _make_clips(tmp_path, count=3)
    settings = _no_commentary_settings(minimal_settings)
    stitch_mock = _patch_common(mocker, tmp_path, clips, _ok_render)

    run_pipeline(settings, dry_run=True)

    paths = stitch_mock.call_args.kwargs["clip_paths"]
    assert [p.name for p in paths] == [
        "1_rendered.mp4",
        "2_rendered.mp4",
        "3_rendered.mp4",
    ]


def test_partial_render_failure_parallel_stitches_remaining(
    mocker, minimal_settings, tmp_path, monkeypatch
):
    """When one clip fails with RENDER_WORKERS=2, the rest still stitch in order."""
    monkeypatch.setenv("RENDER_WORKERS", "2")
    clips = _make_clips(tmp_path, count=3)
    settings = _no_commentary_settings(minimal_settings)

    def render_side_effect(*, input_video, output_video, clip_id=None, **kwargs):
        if clip_id == "2":
            raise RenderClipError(
                "ffmpeg failed",
                command=["ffmpeg", "-y", "-i", "in"],
                returncode=1,
                stderr="detailed stderr",
                stdout="",
                stage="ffmpeg",
            )
        output_video.parent.mkdir(parents=True, exist_ok=True)
        output_video.write_bytes(b"ok")
        return RenderClipResult(output_path=output_video, path_kind="test")

    stitch_mock = _patch_common(mocker, tmp_path, clips, render_side_effect)
    session = run_pipeline(settings, dry_run=True)

    paths = stitch_mock.call_args.kwargs["clip_paths"]
    assert [p.name for p in paths] == ["1_rendered.mp4", "3_rendered.mp4"]

    render_errs = [e for e in session.get("pipeline_errors", []) if e["step"] == "render_clip"]
    assert len(render_errs) == 1
    assert render_errs[0]["clip_id"] == "2"
    assert render_errs[0]["ffmpeg_returncode"] == 1
    assert render_errs[0]["ffmpeg_stderr"] == "detailed stderr"
