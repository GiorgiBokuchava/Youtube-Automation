from youtube_automation.storage.sessions import new_session


def test_new_session_has_timestamp():
    s = new_session({"a": 1})
    assert "created_at" in s
    assert s["a"] == 1
