"""Tests for Reddit yt-dlp auth failure detection and fail-fast sourcing."""

from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.media.video import (
    REDDIT_AUTH_FAILURE_THRESHOLD,
    is_reddit_auth_download_error,
    source_videos,
)


def _minimal_settings() -> dict:
    return {
        "channel": {"name": "test"},
        "final_target_duration": 10,
        "subreddits": ["testsub"],
        "post": {
            "min_duration": 1,
            "max_duration": 60,
            "min_score": 0,
            "min_ratio": 0.0,
            "over_source_pct": 0,
        },
    }


def _make_submission(post_id: str, *, duration: int = 10, score: int = 5000) -> MagicMock:
    submission = MagicMock()
    submission.id = post_id
    submission.is_video = True
    submission.upvote_ratio = 0.99
    submission.score = score
    submission.permalink = f"/r/testsub/comments/{post_id}/title/"
    submission.title = "Test clip"
    submission.selftext = ""
    submission.url = f"https://v.redd.it/{post_id}"
    submission.subreddit.display_name = "testsub"
    submission.author.name = "poster"
    submission.media = {"reddit_video": {"duration": duration}}
    submission.comments.list.return_value = []
    return submission


@pytest.mark.parametrize(
    "message,expected",
    [
        ("DownloadError: Account authentication is required", True),
        ("ERROR: Use --cookies-from-browser or --cookies", True),
        ("HTTP Error 403: Forbidden", False),
        ("Video unavailable", False),
        ("download timeout after 30s", False),
    ],
)
def test_is_reddit_auth_download_error(message: str, expected: bool) -> None:
    assert is_reddit_auth_download_error(RuntimeError(message)) is expected


def test_source_videos_aborts_after_three_auth_failures() -> None:
    submissions = [_make_submission(f"auth{i}") for i in range(5)]
    auth_error = RuntimeError("DownloadError: Account authentication is required")

    with (
        patch("youtube_automation.media.video.ensure_ffmpeg", return_value=None),
        patch("youtube_automation.media.video.create_reddit_client"),
        patch("youtube_automation.media.video.fetch_feed", return_value=submissions),
        patch("youtube_automation.media.video.get_used_video_ids", return_value=set()),
        patch(
            "youtube_automation.media.video._download_reddit_video",
            side_effect=auth_error,
        ) as mock_download,
    ):
        with pytest.raises(RuntimeError, match="authentication errors"):
            source_videos(_minimal_settings())

    assert mock_download.call_count == REDDIT_AUTH_FAILURE_THRESHOLD


def test_source_videos_continues_on_non_auth_failures() -> None:
    submissions = [_make_submission(f"fail{i}") for i in range(4)]
    generic_error = RuntimeError("HTTP Error 404: Not Found")

    with (
        patch("youtube_automation.media.video.ensure_ffmpeg", return_value=None),
        patch("youtube_automation.media.video.create_reddit_client"),
        patch("youtube_automation.media.video.fetch_feed", return_value=submissions),
        patch("youtube_automation.media.video.get_used_video_ids", return_value=set()),
        patch(
            "youtube_automation.media.video._download_reddit_video",
            side_effect=generic_error,
        ) as mock_download,
    ):
        result = source_videos(_minimal_settings())

    assert result == []
    assert mock_download.call_count == 4


def test_source_videos_two_auth_then_non_auth_does_not_abort() -> None:
    submissions = [_make_submission("a1"), _make_submission("a2"), _make_submission("n1")]
    auth_error = RuntimeError("Use --cookies for this URL")
    generic_error = RuntimeError("Video unavailable")

    def download_side_effect(submission, *_args, **_kwargs):
        if submission.id.startswith("a"):
            raise auth_error
        raise generic_error

    with (
        patch("youtube_automation.media.video.ensure_ffmpeg", return_value=None),
        patch("youtube_automation.media.video.create_reddit_client"),
        patch("youtube_automation.media.video.fetch_feed", return_value=submissions),
        patch("youtube_automation.media.video.get_used_video_ids", return_value=set()),
        patch(
            "youtube_automation.media.video._download_reddit_video",
            side_effect=download_side_effect,
        ) as mock_download,
    ):
        result = source_videos(_minimal_settings())

    assert result == []
    assert mock_download.call_count == 3
