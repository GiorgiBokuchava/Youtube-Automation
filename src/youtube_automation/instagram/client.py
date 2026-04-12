from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

import instaloader

from youtube_automation.config.loader import BASE_DIR

logger = logging.getLogger(__name__)

DEFAULT_SESSION_REL = Path("sessions") / "instagram.session"
SESSION_USERNAME_DEFAULT = "instagram"

_SESSION_HELP = (
    "Refresh the Instaloader session: run import_firefox_session.py locally, then "
    "base64-encode sessions/instagram.session and set INSTAGRAM_SESSION_B64 "
    "(or the GitHub Actions secret of the same name)."
)


def session_file_path() -> Path:
    return BASE_DIR / DEFAULT_SESSION_REL


def decode_session(*, env_var: str = "INSTAGRAM_SESSION_B64") -> Path:
    """Decode base64 session from env into ``sessions/instagram.session`` under project root."""
    b64 = os.environ.get(env_var, "").strip()
    if not b64:
        raise RuntimeError(
            f"{env_var} is not set. {_SESSION_HELP}"
        )
    raw = base64.b64decode(b64)
    out = session_file_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    logger.info("Wrote Instaloader session file %s (%d bytes)", out, len(raw))
    return out


def build_loader(
    session_path: Path,
    *,
    download_dir: Path,
    session_username: str = SESSION_USERNAME_DEFAULT,
) -> instaloader.Instaloader:
    """Create a quiet Instaloader, load session, verify login."""
    L = instaloader.Instaloader(
        download_pictures=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        post_metadata_txt_pattern="",
        dirname_pattern=str(download_dir),
        quiet=True,
    )

    if not session_path.is_file():
        raise FileNotFoundError(
            f"Instagram session file missing: {session_path}. {_SESSION_HELP}"
        )

    try:
        L.load_session_from_file(session_username, filename=str(session_path))
        username = L.test_login()
        if not username:
            raise RuntimeError("Session invalid (test_login returned None).")
        logger.info("Instagram session OK, logged in as %s", username)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load Instagram session: {exc}\n{_SESSION_HELP}"
        ) from exc

    return L


def test_session(
    session_path: Path | None = None,
    *,
    session_username: str = SESSION_USERNAME_DEFAULT,
) -> str | None:
    """Return logged-in username if the session works, else None."""
    path = session_path or session_file_path()
    if not path.is_file():
        return None
    try:
        L = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            post_metadata_txt_pattern="",
            quiet=True,
        )
        L.load_session_from_file(session_username, filename=str(path))
        return L.test_login()
    except Exception:
        return None


def ensure_instagram_session_ok(settings: dict) -> None:
    """
    Decode ``INSTAGRAM_SESSION_B64`` when set, else use an on-disk session file.
    Verifies login before sourcing runs.
    """
    ig = settings.get("instagram") or {}
    session_username = str(ig.get("session_username", SESSION_USERNAME_DEFAULT))

    if os.environ.get("INSTAGRAM_SESSION_B64", "").strip():
        path = decode_session()
    else:
        path = session_file_path()
        if not path.is_file():
            raise RuntimeError(
                "Instagram sourcing requires INSTAGRAM_SESSION_B64 or an existing "
                f"{path}. {_SESSION_HELP}"
            )

    user = test_session(path, session_username=session_username)
    if not user:
        raise RuntimeError(
            f"Instagram session check failed for {path}. {_SESSION_HELP}"
        )
