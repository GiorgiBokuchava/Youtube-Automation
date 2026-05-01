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
    "Instagram session: (1) Run `python -m instaloader --login YOUR_USERNAME`, copy the saved "
    "`session-YOUR_USERNAME` file to sessions/instagram.session under the project root, and set "
    "instagram.session_username in YAML to YOUR_USERNAME. "
    "(2) Or put raw session bytes in INSTAGRAM_SESSION_B64 (plain standard base64, no quotes). "
    "If INSTAGRAM_SESSION_B64 is set it overwrites sessions/instagram.session every run unless "
    "you set INSTAGRAM_PREFER_DISK_SESSION=1 to keep the on-disk file. "
    "See https://instaloader.github.io/basic-usage.html"
)


def session_file_path() -> Path:
    return BASE_DIR / DEFAULT_SESSION_REL


def _instagram_b64_from_env(env_var: str) -> str:
    """Normalize INSTAGRAM_SESSION_B64 (trim, strip accidental wrapping quotes / whitespace)."""
    raw = os.environ.get(env_var, "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        raw = raw[1:-1].strip()
    return "".join(raw.split())


def decode_session_raw(b64: str) -> Path:
    """Write decoded session bytes to ``sessions/instagram.session``."""
    if not b64:
        raise RuntimeError(f"Empty session base64. {_SESSION_HELP}")
    try:
        decoded = base64.b64decode(b64, validate=False)
    except Exception as exc:
        raise RuntimeError(
            f"INSTAGRAM_SESSION_B64 is not valid base64: {exc}. {_SESSION_HELP}"
        ) from exc
    out = session_file_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(decoded)
    logger.info("Wrote Instaloader session file %s (%d bytes)", out, len(decoded))
    return out


def decode_session(*, env_var: str = "INSTAGRAM_SESSION_B64") -> Path:
    """Decode base64 session from env into ``sessions/instagram.session`` under project root."""
    b64 = _instagram_b64_from_env(env_var)
    if not b64:
        raise RuntimeError(
            f"{env_var} is not set or empty after stripping. {_SESSION_HELP}"
        )
    return decode_session_raw(b64)


def resolve_instagram_session_path(*, env_var: str = "INSTAGRAM_SESSION_B64") -> Path:
    """
    Path to ``sessions/instagram.session``.

    - If ``INSTAGRAM_PREFER_DISK_SESSION`` is truthy and the file exists, use it (skip env decode).
    - Else if ``INSTAGRAM_SESSION_B64`` is non-empty, decode it (overwrites on-disk file).
    - Else use on-disk path only.
    """
    disk = session_file_path()
    b64 = _instagram_b64_from_env(env_var)
    prefer_disk = os.environ.get(
        "INSTAGRAM_PREFER_DISK_SESSION", ""
    ).strip().lower() in (
        "1",
        "true",
        "yes",
    )

    if prefer_disk:
        if disk.is_file():
            logger.info(
                "Instagram: using on-disk session %s (INSTAGRAM_PREFER_DISK_SESSION)",
                disk,
            )
            return disk
        if b64:
            logger.warning(
                "INSTAGRAM_PREFER_DISK_SESSION set but %s missing; decoding %s instead.",
                disk,
                env_var,
            )

    if b64:
        logger.info(
            "Instagram: decoding %s into %s (set INSTAGRAM_PREFER_DISK_SESSION=1 or clear %s "
            "to use a manually copied file without overwriting)",
            env_var,
            disk,
            env_var,
        )
        return decode_session_raw(b64)

    return disk


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
        dirname_pattern=str(download_dir / "{target}"),
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
        detail = str(exc).lower()
        hints: list[str] = []
        if (
            "getaddrinfo" in detail
            or "nameresolutionerror" in detail
            or "11001" in detail
            or "name or service not known" in detail
        ):
            hints.append(
                "Network/DNS: hostname lookup failed for instagram.com — check connectivity, VPN, "
                "DNS settings, or firewall (this is not a session-file bug)."
            )
        if "401" in detail or "unauthorized" in detail:
            hints.append(
                "HTTP 401 from Instagram — often rate-limit / cooldown; wait and retry, refresh "
                "session after DNS works, avoid parallel scrapers hitting IG."
            )
        suffix = ("\n" + "\n".join(hints)) if hints else ""
        raise RuntimeError(
            f"Failed to load Instagram session: {exc}{suffix}\n{_SESSION_HELP}"
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

    path = resolve_instagram_session_path()
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
