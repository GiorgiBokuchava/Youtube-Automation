from youtube_automation.ai.text.shorts_commentary import _strip_ai_rank_echo


def test_strip_echo_only_matching_rank():
    assert _strip_ai_rank_echo('3. hello there', 3) == "hello there"
    assert _strip_ai_rank_echo('12) wow', 12) == "wow"


def test_strip_preserves_leading_digit_when_wrong_rank():
    assert _strip_ai_rank_echo("2 dogs running", 3) == "2 dogs running"
