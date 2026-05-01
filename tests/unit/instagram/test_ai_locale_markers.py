from youtube_automation.instagram.scraper import (
    _caption_or_comments_signal_ai,
    _text_contains_ai_locale_marker,
)


def test_detects_ai_token():
    assert _text_contains_ai_locale_marker("looks AI generated")


def test_detects_ia_romance_locale():
    assert _text_contains_ai_locale_marker("esto es IA generado")
    assert _text_contains_ai_locale_marker("l'IA est partout")


def test_detects_russian_ii_token():
    assert _text_contains_ai_locale_marker("это ИИ видео")


def test_avoids_substrings_aid_fail_email():
    assert not _text_contains_ai_locale_marker("AID mission complete")
    assert not _text_contains_ai_locale_marker("FAIL 😭")
    assert not _text_contains_ai_locale_marker("email me pics")


def test_caption_or_comments_any_source():
    assert _caption_or_comments_signal_ai(caption="", comment_texts=["pure IA"])
    assert _caption_or_comments_signal_ai(caption="Made with IA", comment_texts=[])
    assert _caption_or_comments_signal_ai(caption="", comment_texts=["ИИ fake"])
    assert not _caption_or_comments_signal_ai(caption="", comment_texts=[])


def test_empty_or_whitespace_text():
    assert not _text_contains_ai_locale_marker("")
    assert not _text_contains_ai_locale_marker("   ")
