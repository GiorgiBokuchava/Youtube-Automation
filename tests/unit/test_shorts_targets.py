from youtube_automation.ai.text.shorts_topic import sanitize_shorts_topic_title
from youtube_automation.shorts_pipeline import _estimated_shorts_compilation_sec, _shorts_targets_met


def test_sanitize_animls_typo():
    assert "Animals" in sanitize_shorts_topic_title("These {count} Animls Are Broken")


def test_targets_met_clip_minimum_only():
    ok, _ = _shorts_targets_met(
        clip_count=5,
        estimated_sec=10.0,
        settings={"shorts": {"clip_count_min": 5}},
    )
    assert ok


def test_targets_met_duration_or_gate():
    ok, detail = _shorts_targets_met(
        clip_count=3,
        estimated_sec=65.0,
        settings={"shorts": {"clip_count_min": 5, "target_compilation_duration_sec": 60}},
    )
    assert ok
    assert "65.0" in detail and "60.0" in detail


def test_targets_fail_when_below_both():
    ok, _ = _shorts_targets_met(
        clip_count=2,
        estimated_sec=20.0,
        settings={"shorts": {"clip_count_min": 5, "target_compilation_duration_sec": 60}},
    )
    assert not ok


def test_estimated_runtime_caps_segments():
    clips = [{"duration_sec": 100}, {"duration_sec": 5}]
    assert _estimated_shorts_compilation_sec(clips, 10.0) == 15.0
