from youtube_automation.utils.text_sanitize import sanitize_plain_english_tts


def test_strips_emojis_and_keeps_ascii():
    s = "Hello 😂 world 🐶 test"
    assert sanitize_plain_english_tts(s) == "Hello world test"


def test_collapses_whitespace():
    assert sanitize_plain_english_tts("  a   b  \n c  ") == "a b c"


def test_keeps_basic_punctuation():
    s = "Wait, really? It's fine — well, \"ok\"."
    # em dash removed (not in whitelist)
    out = sanitize_plain_english_tts(s)
    assert "Wait" in out and "really" in out
    assert "It's" in out or "Its" in out  # apostrophe kept


def test_empty_after_only_emoji():
    assert sanitize_plain_english_tts("😂🔥") == ""
