from youtube_automation.ai.text.shorts_topic import generate_shorts_topic


def test_generate_shorts_topic_respects_fixed_clip_count(mocker):
    settings = {
        "channel": {"niche": "dashcam"},
        "shorts": {"clip_count": 4, "randomize_clip_count": False},
    }
    mocker.patch(
        "youtube_automation.ai.text.service.text_service.generate",
        return_value='{"topic_title":"Road Chaos","search_queries":["dashcam crash","near miss","bad drivers"],"clip_count":9}',
    )

    plan = generate_shorts_topic(settings)

    assert plan.clip_count == 4

