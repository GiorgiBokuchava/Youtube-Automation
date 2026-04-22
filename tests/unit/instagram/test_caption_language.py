from youtube_automation.instagram.scraper import _is_likely_english


def test_caption_language_accepts_english_text():
    assert _is_likely_english("This dog is so cute and funny")


def test_caption_language_rejects_non_latin_text():
    assert not _is_likely_english("这是一个非常可爱的动物视频")


def test_caption_language_accepts_emoji_only_caption():
    assert _is_likely_english("😂🐶❤️")
