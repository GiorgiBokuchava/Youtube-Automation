"""Unit tests for multi-source video sourcing."""

from unittest.mock import patch

from youtube_automation.instagram import scraper as ig_scraper
from youtube_automation.sourcing import (
    _interleave_weighted,
    instagram_sourcing_enabled,
    source_all_videos,
)


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
        with patch.object(ig_scraper, "source_instagram_videos") as mock_i:
            source_all_videos(settings)
    assert mock_r.call_count >= 1
    cap_kw = mock_r.call_args_list[0][1]
    assert cap_kw["duration_cap_seconds"] > 0
    mock_i.assert_not_called()


def test_source_all_top_up_switches_to_instagram_when_reddit_exhausted():
    settings = {
        "channel": {"name": "test"},
        "final_target_duration": 1,
        "post": {"over_source_pct": 0},
        "subreddits": ["pics"],
        "source_split": {"reddit": 0.5, "instagram": 0.5},
        "instagram": {"hashtags": ["cats"]},
    }

    reddit_clip = [
        {"id": "r1", "duration_sec": 10, "source": "reddit"},
    ]
    instagram_clips = [
        {"id": "i1", "duration_sec": 25, "source": "instagram"},
        {"id": "i2", "duration_sec": 30, "source": "instagram"},
    ]

    with patch("youtube_automation.media.video.source_videos") as mock_r:
        mock_r.side_effect = [reddit_clip, []]
        with patch.object(ig_scraper, "source_instagram_videos") as mock_i:
            mock_i.side_effect = [[], instagram_clips]
            clips = source_all_videos(settings)

    ids = [c["id"] for c in clips]
    assert "r1" in ids
    assert "i1" in ids
    assert "i2" in ids
    assert mock_i.call_count >= 2


def test_interleave_weighted_balances_sources():
    reddit = [{"id": "r1"}, {"id": "r2"}, {"id": "r3"}]
    instagram = [{"id": "i1"}, {"id": "i2"}, {"id": "i3"}]

    merged = _interleave_weighted(reddit, instagram, 0.5, 0.5)
    ids = [clip["id"] for clip in merged]

    assert ids == ["r1", "i1", "r2", "i2", "r3", "i3"]
