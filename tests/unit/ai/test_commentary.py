from youtube_automation.ai.text.commentary import generate_commentary_video_first


def test_video_first_fallback_to_text(mocker, dummy_video):
    mocker.patch(
        "youtube_automation.ai.text.service.text_service.generate",
        side_effect=["video result"],
    )

    res = generate_commentary_video_first(
        video_path=dummy_video, title="dog", selftext="", top_comments=[]
    )

    assert res
