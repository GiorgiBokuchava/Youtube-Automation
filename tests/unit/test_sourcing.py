"""Unit tests for multi-source video sourcing."""

from unittest.mock import MagicMock, patch

from youtube_automation.sourcing import instagram_sourcing_enabled, source_all_videos


def test_instagram_sourcing_enabled_requires_split_and_hashtags():
    assert not instagram_sourcing_enabled({})
    assert not instagram_sourcing_enabled(
        {"source_split": {"instagram": 0.5}, "instagram": {"hashtags": []}}
    )
    assert instagram_sourcing_enabled(
        {
            "source_split": {"instagram": 0.5},
            "instagram": {"hashtags": ["cats"]},
        }
    )


def test_source_all_renormalizes_when_instagram_disabled():
    """If YAML keeps instagram weight but omits hashtags, Reddit gets full budget."""
    settings = {
        "channel": {"name": "test"},
        "final_target_duration": 10,
        "post": {"over_source_pct": 0},
        "subreddits": ["pics"],
        "source_split": {"reddit": 0.6, "instagram": 0.4},
        "instagram": {"hashtags": []},
    }
    with patch("youtube_automation.media.video.source_videos") as mock_r:
        mock_r.return_value = []
        with patch("youtube_automation.instagram.scraper.source_instagram_videos") as mock_i:
            source_all_videos(settings)
    mock_r.assert_called_once()
    cap_kw = mock_r.call_args[1]
    assert cap_kw["duration_cap_seconds"] > 0
    mock_i.assert_not_called()
