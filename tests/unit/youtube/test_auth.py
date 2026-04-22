import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from youtube_automation.youtube.auth import (
    ensure_youtube_refresh_token,
    load_credentials,
)


def test_load_credentials_strips_whitespace(monkeypatch):
    monkeypatch.setenv("YT_CLIENT_ID", "  my-id \n")
    monkeypatch.setenv("YT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("YT_REFRESH_TOKEN", "token")
    c = load_credentials()
    assert c.client_id == "my-id"


def test_load_credentials_missing(monkeypatch):
    monkeypatch.delenv("YT_REFRESH_TOKEN", raising=False)
    monkeypatch.setenv("YT_CLIENT_ID", "id")
    monkeypatch.setenv("YT_CLIENT_SECRET", "secret")
    with pytest.raises(RuntimeError, match="Missing or empty"):
        load_credentials()


def test_ensure_youtube_refresh_token_wraps_refresh_error(monkeypatch, mocker):
    monkeypatch.setenv("YT_CLIENT_ID", "id")
    monkeypatch.setenv("YT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("YT_REFRESH_TOKEN", "token")
    mocker.patch.object(
        Credentials,
        "refresh",
        side_effect=RefreshError("invalid_grant: Bad Request"),
    )
    with pytest.raises(RuntimeError) as excinfo:
        ensure_youtube_refresh_token()
    msg = str(excinfo.value)
    assert "refresh failed" in msg.lower() or "invalid_grant" in msg
    assert "Testing" in msg
