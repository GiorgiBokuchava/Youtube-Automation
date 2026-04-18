from youtube_automation.ai.text.shorts_commentary import (
    generate_shorts_commentary,
    generate_shorts_overlay_commentary,
    normalize_short_caption,
)


def test_normalize_short_caption_clamps_to_five_words():
    assert normalize_short_caption("this is way too many words now") == "this is way too many"


def test_generate_shorts_commentary_fallback_when_model_empty(mocker):
    mocker.patch(
        "youtube_automation.ai.text.service.text_service.generate",
        return_value="  ",
    )

    caption = generate_shorts_commentary("clip title", "dashcam")

    assert caption == "Wait for it..."


def test_generate_shorts_overlay_commentary(mocker):
    settings = {
        "channel": {"niche": "dashcam", "name": "dashcam"},
        "shorts": {"overlay_comment_max_words": 5},
        "post_context": {},
    }
    clip = {
        "title": "Test",
        "subreddit": "Dashcam",
        "score": 100,
        "duration_sec": 12,
        "commentary_context": {
            "post_title": "Test",
            "post_selftext": "",
            "top_comments": ["funny"],
        },
    }
    mocker.patch(
        "youtube_automation.ai.text.service.text_service.generate",
        return_value="Way too close",
    )
    out = generate_shorts_overlay_commentary(
        settings,
        clip,
        topic_title="Fails",
        video_main_title="Top 5",
        segment_rank=1,
        total_segments=5,
    )
    assert out == "Way too close"


def test_generate_shorts_overlay_commentary_caps_words(mocker):
    settings = {
        "channel": {"niche": "dashcam", "name": "dashcam"},
        "shorts": {},
        "post_context": {},
    }
    clip = {
        "title": "Test",
        "subreddit": "Dashcam",
        "score": 100,
        "duration_sec": 12,
        "commentary_context": {
            "post_title": "Test",
            "post_selftext": "",
            "top_comments": [],
        },
    }
    mocker.patch(
        "youtube_automation.ai.text.service.text_service.generate",
        return_value="one two three four five six seven eight",
    )
    out = generate_shorts_overlay_commentary(
        settings,
        clip,
        topic_title="Fails",
        video_main_title="Top 5",
        segment_rank=1,
        total_segments=5,
    )
    assert out == "one two three four five"

