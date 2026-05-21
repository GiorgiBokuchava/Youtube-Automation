import pytest

from youtube_automation.pipeline import (
    InsufficientSourceDurationError,
    assert_sufficient_source_duration,
    min_required_source_seconds,
)


def _settings(**overrides):
    base = {
        "final_target_duration": 2,
        "post": {
            "enforce_min_source_duration": True,
            "min_source_duration_ratio": 1.0,
        },
    }
    base.update(overrides)
    return base


def test_min_required_source_seconds_from_target():
    assert min_required_source_seconds(_settings()) == 120


def test_assert_passes_when_sourced_meets_target():
    clips = [{"duration_sec": 60}, {"duration_sec": 70}]
    assert_sufficient_source_duration(_settings(), clips)


def test_assert_raises_when_sourced_below_target():
    clips = [{"duration_sec": 30}, {"duration_sec": 20}]
    with pytest.raises(InsufficientSourceDurationError, match="Insufficient sourced"):
        assert_sufficient_source_duration(_settings(), clips)


def test_skips_when_target_duration_zero():
    assert_sufficient_source_duration(
        _settings(final_target_duration=0),
        [{"duration_sec": 5}],
    )


def test_skips_when_enforcement_disabled():
    assert_sufficient_source_duration(
        _settings(post={"enforce_min_source_duration": False}),
        [{"duration_sec": 1}],
    )


def test_ratio_allows_partial_target():
    clips = [{"duration_sec": 90}]
    assert_sufficient_source_duration(
        _settings(post={"min_source_duration_ratio": 0.75}),
        clips,
    )
    with pytest.raises(InsufficientSourceDurationError):
        assert_sufficient_source_duration(
            _settings(post={"min_source_duration_ratio": 0.75}),
            [{"duration_sec": 80}],
        )
