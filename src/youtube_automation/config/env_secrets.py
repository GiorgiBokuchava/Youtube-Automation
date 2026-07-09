"""Decode base64 credentials from .env into ephemeral temp files.

Libraries (yt-dlp, Instaloader) require file paths; users configure only
``REDDIT_COOKIES`` and ``INSTAGRAM_SESSION_B64`` in ``.env`` / GitHub secrets.
"""

from __future__ import annotations

import base64
import logging
import os
import pickle
import tempfile
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_INSTAGRAM_HELP = (
    "Set INSTAGRAM_SESSION_B64 in .env (base64 Instaloader session pickle). "
    "Generate with: python scripts/encode_instagram_session_b64.py --cookies path/to/cookies.txt --env"
)
_REDDIT_HELP = (
    "Set REDDIT_COOKIES in .env (base64 Netscape cookie export). "
    "Generate with: python scripts/encode_reddit_cookies_b64.py --cookies path/to/cookies.txt --env"
)


def read_b64_env(name: str) -> str:
    raw = os.environ.get(name, "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        raw = raw[1:-1].strip()
    return "".join(raw.split())


def decode_b64_env(name: str) -> bytes:
    b64 = read_b64_env(name)
    if not b64:
        raise RuntimeError(f"{name} is unset or empty.")
    errors: list[Exception] = []
    for validate in (True, False):
        try:
            return base64.b64decode(b64, validate=validate)
        except Exception as exc:
            errors.append(exc)
    raise RuntimeError(f"{name} is not valid base64 ({errors[-1]}).") from errors[-1]


def validate_instagram_session_bytes(data: bytes) -> None:
    try:
        session = pickle.loads(data)
    except Exception as exc:
        raise RuntimeError(f"Instagram session pickle unreadable: {exc}") from exc
    if not isinstance(session, dict):
        raise RuntimeError(
            f"Instagram session must be a cookie dict, got {type(session).__name__}."
        )
    if not str(session.get("csrftoken") or "").strip():
        raise RuntimeError("Instagram session missing csrftoken.")
    if not str(session.get("sessionid") or "").strip():
        raise RuntimeError("Instagram session missing sessionid.")


def _write_temp_file(*, prefix: str, suffix: str, data: bytes) -> Path:
    fd, raw_path = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    path = Path(raw_path)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


@lru_cache(maxsize=1)
def get_reddit_cookies_path() -> Path | None:
    """Netscape cookie file decoded from ``REDDIT_COOKIES``, or ``None`` if unset."""
    if not read_b64_env("REDDIT_COOKIES"):
        return None
    data = decode_b64_env("REDDIT_COOKIES")
    path = _write_temp_file(prefix="reddit_cookies_", suffix=".txt", data=data)
    logger.debug("Reddit cookies materialized from REDDIT_COOKIES (%d bytes)", len(data))
    return path


@lru_cache(maxsize=1)
def get_instagram_session_path() -> Path:
    """Instaloader session pickle decoded from ``INSTAGRAM_SESSION_B64``."""
    data = decode_b64_env("INSTAGRAM_SESSION_B64")
    validate_instagram_session_bytes(data)
    path = _write_temp_file(prefix="instagram_session_", suffix=".session", data=data)
    logger.debug(
        "Instagram session materialized from INSTAGRAM_SESSION_B64 (%d bytes)", len(data)
    )
    return path


def materialize_env_secrets() -> None:
    """Prepare ephemeral credential files after ``load_env`` (no-op if vars unset)."""
    get_reddit_cookies_path()
    if read_b64_env("INSTAGRAM_SESSION_B64"):
        get_instagram_session_path()
