from types import SimpleNamespace

from youtube_automation.media.thumbnail import (
    _max_selftext_words,
    _selftext_skip_reason,
)


def test_max_selftext_words_prefers_yaml_key():
    assert _max_selftext_words({"max_selftext_words": 12}) == 12


def test_max_selftext_words_legacy_fallback():
    assert _max_selftext_words({"max_description_words": 8}) == 8


def test_require_no_selftext_rejects_nonempty():
    s = SimpleNamespace(selftext="Hello world")
    assert (
        _selftext_skip_reason({"require_no_selftext": True}, s)
        == "selftext present (require_no_selftext)"
    )


def test_require_no_selftext_allows_empty():
    s = SimpleNamespace(selftext="")
    assert _selftext_skip_reason({"require_no_selftext": True}, s) is None


def test_max_selftext_words_limit():
    s = SimpleNamespace(selftext="one two three four five")
    assert _selftext_skip_reason({"max_selftext_words": 3}, s) is not None
