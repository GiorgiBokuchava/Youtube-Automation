import pytest
from youtube_automation.ai.text.commentary import generate_commentary_video_first


def test_video_commentary_succeeds(mocker, dummy_video):
    mocker.patch(
        "youtube_automation.ai.text.service.text_service.generate",
        return_value="video result",
    )

    text, model, fallback = generate_commentary_video_first(
        video_path=dummy_video, title="dog does a backflip", top_comments=["lol"]
    )

    assert text == "video result"
    assert fallback is False


def test_falls_back_to_title_when_video_fails(mocker, dummy_video):
    mocker.patch(
        "youtube_automation.ai.text.service.text_service.generate",
        side_effect=RuntimeError("no provider"),
    )

    text, model, fallback = generate_commentary_video_first(
        video_path=dummy_video,
        title="Dog does the funniest thing ever",
        top_comments=["this is great"],
    )

    # Title is tried first
    assert text == "Dog does the funniest thing ever"
    assert model == "text_fallback"
    assert fallback is True


def test_skips_dirty_title_uses_comment(mocker, dummy_video):
    mocker.patch(
        "youtube_automation.ai.text.service.text_service.generate",
        side_effect=RuntimeError("no provider"),
    )

    text, model, fallback = generate_commentary_video_first(
        video_path=dummy_video,
        title="this fucking dog",         # banned word → skipped
        top_comments=["clean comment here"],
    )

    assert text == "clean comment here"
    assert fallback is True


def test_skips_too_long_title_uses_comment(mocker, dummy_video):
    mocker.patch(
        "youtube_automation.ai.text.service.text_service.generate",
        side_effect=RuntimeError("no provider"),
    )

    long_title = " ".join(["word"] * 15)   # 15 words > 12 limit

    text, model, fallback = generate_commentary_video_first(
        video_path=dummy_video,
        title=long_title,
        top_comments=["short comment"],
    )

    assert text == "short comment"
    assert fallback is True


def test_raises_when_nothing_clean(mocker, dummy_video):
    mocker.patch(
        "youtube_automation.ai.text.service.text_service.generate",
        side_effect=RuntimeError("no provider"),
    )

    with pytest.raises(RuntimeError, match="No video commentary"):
        generate_commentary_video_first(
            video_path=dummy_video,
            title="this fucking dog",      # banned
            top_comments=["shit happens"], # banned
        )
