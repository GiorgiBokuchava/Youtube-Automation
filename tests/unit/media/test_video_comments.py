"""Tests for Reddit comment extraction in video sourcing."""

from unittest.mock import MagicMock

from youtube_automation.media.video import _extract_comments_for_clip, _word_count


def test_word_count():
    assert _word_count("") == 0
    assert _word_count("hello") == 1
    assert _word_count("one two three") == 3
    assert _word_count("  lots   of    spaces  ") == 3


def _mock_comment(body: str):
    c = MagicMock()
    c.body = body
    return c


def test_extract_top_comments_respects_max_words():
    sub = MagicMock()
    sub.comment_sort = None
    sub.comments.replace_more = MagicMock()
    # Reddit "top" order: long first, then short ones
    sub.comments.list = MagicMock(
        return_value=[
            _mock_comment("one two three four five six eight nine"),  # 8 words — skip
            _mock_comment("short and sweet"),  # 3 words — keep
            _mock_comment("a b c d e f g h"),  # 8 words — skip
            _mock_comment("exactly seven words in this comment here"),  # 7 words — keep
            _mock_comment("tiny"),  # 1 word — keep
            _mock_comment("two words"),  # 2 words — keep
        ]
    )

    top = _extract_comments_for_clip(
        sub,
        context_limit=5,
        context_max_len=180,
        context_max_words=7,
    )

    assert top == [
        "short and sweet",
        "exactly seven words in this comment here",
        "tiny",
        "two words",
    ]
    assert len(top) < 5  # only 4 qualifying comments in the mock list


def test_extract_context_no_word_limit_takes_first_n():
    sub = MagicMock()
    sub.comments.replace_more = MagicMock()
    sub.comments.list = MagicMock(
        return_value=[
            _mock_comment("first long " + "word " * 20),
            _mock_comment("second"),
        ]
    )

    top = _extract_comments_for_clip(
        sub,
        context_limit=2,
        context_max_len=180,
        context_max_words=None,
    )

    assert len(top) == 2
    assert top[0].startswith("first long")
