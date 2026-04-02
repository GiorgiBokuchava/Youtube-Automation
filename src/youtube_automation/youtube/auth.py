import os

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

_YT_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _env_strip(key: str) -> str | None:
    raw = os.getenv(key)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped if stripped else None


def load_credentials() -> Credentials:
    refresh = _env_strip("YT_REFRESH_TOKEN")
    client_id = _env_strip("YT_CLIENT_ID")
    client_secret = _env_strip("YT_CLIENT_SECRET")
    if not refresh or not client_id or not client_secret:
        raise RuntimeError(
            "Missing or empty YT_REFRESH_TOKEN, YT_CLIENT_ID, or YT_CLIENT_SECRET. "
            "GitHub Actions: check repository/environment secrets; accidental newlines "
            "are stripped but values must be non-empty."
        )
    return Credentials(
        None,
        refresh_token=refresh,
        token_uri=_TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=[_YT_UPLOAD_SCOPE],
    )


def ensure_youtube_refresh_token() -> None:
    """
    Perform one access-token refresh so invalid_grant fails before expensive pipeline work.

    Repeated weekly failures in CI are usually:
    - OAuth consent screen still in \"Testing\" (refresh tokens can expire in ~7 days), or
    - refresh token regenerated with a different client id/secret than in secrets.
    """
    creds = load_credentials()
    try:
        creds.refresh(Request())
    except RefreshError as e:
        raise RuntimeError(
            "YouTube OAuth refresh failed (invalid_grant). The refresh token is not "
            "accepted for this client id/secret.\n\n"
            "What to do:\n"
            "1. Re-copy YT_CLIENT_ID, YT_CLIENT_SECRET, and YT_REFRESH_TOKEN from the "
            "same Google Cloud OAuth 2.0 Client; update GitHub Actions secrets (same "
            "names on each Environment if you use deployment environments).\n"
            "2. In Google Cloud Console → APIs & Services → OAuth consent screen: if "
            "the app is in Testing, refresh tokens often stop working after about seven "
            "days. Publish to Production (or complete verification if Google requires "
            "it for youtube.upload) so tokens last until you revoke them.\n"
            "3. Regenerate a new refresh token with the OAuth playground or a small "
            "local script using this client, then set YT_REFRESH_TOKEN again.\n\n"
            f"Underlying error: {e}"
        ) from e
