import base64
import pickle

import pytest

from youtube_automation.config import env_secrets


@pytest.fixture(autouse=True)
def _clear_secret_caches():
    env_secrets.get_reddit_cookies_path.cache_clear()
    env_secrets.get_instagram_session_path.cache_clear()
    yield
    env_secrets.get_reddit_cookies_path.cache_clear()
    env_secrets.get_instagram_session_path.cache_clear()


def test_read_b64_env_strips_quotes_and_whitespace(monkeypatch):
    monkeypatch.setenv("REDDIT_COOKIES", ' "YWJj\n" ')
    assert env_secrets.read_b64_env("REDDIT_COOKIES") == "YWJj"


def test_get_reddit_cookies_path_none_when_unset(monkeypatch):
    monkeypatch.delenv("REDDIT_COOKIES", raising=False)
    assert env_secrets.get_reddit_cookies_path() is None


def test_get_reddit_cookies_path_writes_netscape_file(monkeypatch, tmp_path):
    raw = b"# Netscape HTTP Cookie File\n.reddit.com\tTRUE\t/\tTRUE\t0\treddit_session\tabc\n"
    monkeypatch.setenv("REDDIT_COOKIES", base64.b64encode(raw).decode("ascii"))
    path = env_secrets.get_reddit_cookies_path()
    assert path is not None
    assert path.read_bytes() == raw


def test_get_instagram_session_path_validates_pickle(monkeypatch):
    good = pickle.dumps({"sessionid": "sid", "csrftoken": "csrf"})
    monkeypatch.setenv("INSTAGRAM_SESSION_B64", base64.b64encode(good).decode("ascii"))
    path = env_secrets.get_instagram_session_path()
    assert path.read_bytes() == good


def test_get_instagram_session_path_rejects_bad_pickle(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_SESSION_B64", base64.b64encode(b"not-a-pickle").decode("ascii"))
    with pytest.raises(RuntimeError, match="pickle"):
        env_secrets.get_instagram_session_path()


def test_decode_b64_env_rejects_garbage(monkeypatch):
    monkeypatch.setenv("REDDIT_COOKIES", "!!!not-base64!!!")
    with pytest.raises(RuntimeError, match="not valid base64"):
        env_secrets.decode_b64_env("REDDIT_COOKIES")
