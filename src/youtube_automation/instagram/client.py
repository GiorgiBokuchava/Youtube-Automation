from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import instaloader

from youtube_automation.config.env_secrets import (
    _INSTAGRAM_HELP,
    get_instagram_session_path,
    read_b64_env,
)

logger = logging.getLogger(__name__)

SESSION_USERNAME_DEFAULT = "instagram"

_SESSION_HELP = (
    "Instagram requires INSTAGRAM_SESSION_B64 in .env (base64 Instaloader session pickle). "
    "Generate: python scripts/encode_instagram_session_b64.py --cookies path/to/cookies.txt --env. "
    "YAML instagram.session_username must match the logged-in account. "
    "If Instagram returns checkpoint_required, complete the security check in app/web, "
    "export a fresh session, and update .env. "
    "INSTAGRAM_SKIP_TEST_LOGIN=1 skips the probe only (downloads may still fail)."
)


def _env_truthy_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def resolve_instagram_session_path(
    *,
    env_var: str = "INSTAGRAM_SESSION_B64",
    session_username: str | None = None,
) -> Path:
    """Return ephemeral session path decoded from ``INSTAGRAM_SESSION_B64`` in .env."""
    del session_username  # kept for API compatibility; username comes from YAML at load time
    if env_var != "INSTAGRAM_SESSION_B64":
        raise RuntimeError(f"Unsupported env_var {env_var!r}; use INSTAGRAM_SESSION_B64.")
    if not read_b64_env(env_var):
        raise RuntimeError(f"{env_var} is unset or empty. {_INSTAGRAM_HELP}")
    try:
        path = get_instagram_session_path()
    except RuntimeError as exc:
        raise RuntimeError(f"{exc}\n{_SESSION_HELP}") from exc
    logger.info("Instagram: session ready from %s (%d bytes b64)", env_var, len(read_b64_env(env_var)))
    return path


def _bare_instaloader(download_dir: Path | None) -> instaloader.Instaloader:
    kw: dict = dict(
        download_pictures=False,
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        post_metadata_txt_pattern="",
        quiet=True,
    )
    if download_dir is not None:
        kw["dirname_pattern"] = str(download_dir / "{target}")
    return instaloader.Instaloader(**kw)


# Verified :class:`InstaloaderContext` from the last successful session probe (same process).
_verified_stamp: tuple[str, float, str] | None = None
_verified_context: instaloader.InstaloaderContext | None = None


def _session_verify_stamp(session_path: Path, session_username: str) -> tuple[str, float, str]:
    return (str(session_path.resolve()), session_path.stat().st_mtime, session_username)


def _remember_verified_loader(L: instaloader.Instaloader, session_path: Path, session_username: str) -> None:
    global _verified_stamp, _verified_context
    _verified_stamp = _session_verify_stamp(session_path, session_username)
    _verified_context = L.context


def _instagram_lists_from_settings(ig: dict) -> tuple[list[str], list[str]]:
    hashtags = [
        str(h).lstrip("#").strip() for h in (ig.get("hashtags") or []) if str(h).strip()
    ]
    accounts = [
        str(a).lstrip("@").strip() for a in (ig.get("accounts") or []) if str(a).strip()
    ]
    return hashtags, accounts


def _probe_hashtag_web_info(L: instaloader.Instaloader, keyword: str) -> None:
    """Single ``api/v1/tags/web_info/`` request (same family as sourcing; not the logged-in feed)."""
    params = {"__a": 1, "__d": "dis", "tag_name": keyword}
    try:
        resp = L.context.get_iphone_json("api/v1/tags/web_info/", params)
    except Exception as exc:
        raise RuntimeError(
            f"Instagram session probe failed (#{keyword}): {exc}\n{_SESSION_HELP}"
        ) from exc
    if not isinstance(resp, dict):
        raise RuntimeError(
            f"Instagram session probe: bad response type for #{keyword}: {type(resp).__name__}. "
            f"{_SESSION_HELP}"
        )
    if resp.get("data") is None:
        raise RuntimeError(
            f"Instagram session probe: no data for #{keyword} (status={resp.get('status')!r}). "
            f"{_SESSION_HELP}"
        )


def _probe_profile_username(L: instaloader.Instaloader, username: str) -> None:
    profile = instaloader.Profile.from_username(L.context, username)
    _ = profile.userid


def _probe_instagram_session(L: instaloader.Instaloader, ig: dict) -> None:
    if _env_truthy_flag("INSTAGRAM_SKIP_TEST_LOGIN"):
        logger.warning(
            "INSTAGRAM_SKIP_TEST_LOGIN is set — skipping Instagram session probe "
            "(use only when the API is flaky; downloads may still fail)."
        )
        return
    hashtags, accounts = _instagram_lists_from_settings(ig)
    if hashtags:
        _probe_hashtag_web_info(L, hashtags[0])
        return
    if accounts:
        try:
            _probe_profile_username(L, accounts[0])
            return
        except instaloader.exceptions.PrivateProfileNotFollowedException:
            logger.warning(
                "Instagram session probe: @%s not visible with this session; probing #instagram",
                accounts[0],
            )
    _probe_hashtag_web_info(L, "instagram")


def _instagram_exception_text(exc: BaseException) -> str:
    parts: list[str] = [str(exc)]
    cur: BaseException | None = exc
    while cur and cur.__cause__ is not None:
        cur = cur.__cause__
        parts.append(str(cur))
    return " ".join(parts).lower()


def _is_checkpoint_required(exc: BaseException) -> bool:
    return "checkpoint_required" in _instagram_exception_text(exc)


def _is_nonretryable_instagram(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            instaloader.exceptions.BadCredentialsException,
            FileNotFoundError,
        ),
    ):
        return True
    return _is_checkpoint_required(exc)


def _is_transient_instagram_failure(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            instaloader.exceptions.TooManyRequestsException,
            instaloader.exceptions.ConnectionException,
        ),
    ):
        return True
    msg = str(exc).lower()
    return (
        "401" in msg
        or "403" in msg
        or "few minutes" in msg
        or "please wait" in msg
        or "too many requests" in msg
        or "rate limit" in msg
        or "feedback_required" in msg
    )


def _load_session_and_probe(
    L: instaloader.Instaloader,
    session_path: Path,
    session_username: str,
    instagram_settings: dict,
) -> None:
    if not session_path.is_file():
        raise FileNotFoundError(
            f"Instagram session path missing at {session_path}. {_SESSION_HELP}"
        )
    try:
        L.load_session_from_file(session_username, filename=str(session_path))
        _probe_instagram_session(L, instagram_settings)
    except FileNotFoundError:
        raise
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
                "DNS, or firewall."
            )
        if "401" in detail or "unauthorized" in detail or "few minutes" in detail:
            hints.append(
                "Instagram 401 / wait — cool down and refresh INSTAGRAM_SESSION_B64 in .env. "
                "Datacenter IPs (GitHub Actions) often struggle; export from home network. "
                "INSTAGRAM_SKIP_TEST_LOGIN=1 skips the probe only."
            )
        if "checkpoint_required" in detail:
            hints.append(
                "Instagram checkpoint — open the Instagram app or instagram.com, complete the security "
                "check, then export a NEW session (same account) from a normal home/mobile network and "
                "update INSTAGRAM_SESSION_B64. CI/datacenter IPs often trigger this; skipping probe "
                "(INSTAGRAM_SKIP_TEST_LOGIN=1) may allow some iPhone API calls but can still fail later."
            )
        suffix = ("\n" + "\n".join(hints)) if hints else ""
        raise RuntimeError(
            f"Failed Instagram session authentication: {exc}{suffix}\n{_SESSION_HELP}"
        ) from exc


def build_loader(
    session_path: Path,
    *,
    download_dir: Path,
    session_username: str = SESSION_USERNAME_DEFAULT,
    instagram_settings: dict | None = None,
) -> instaloader.Instaloader:
    ig_probe = instagram_settings if instagram_settings is not None else {}
    L = _bare_instaloader(download_dir)
    stamp = _session_verify_stamp(session_path, session_username)
    if _verified_stamp == stamp and _verified_context is not None:
        L.context = _verified_context
        logger.info(
            "Instagram: reusing verified session for %s (same file mtime)",
            session_username,
        )
        return L

    _load_session_and_probe(L, session_path, session_username, ig_probe)
    _remember_verified_loader(L, session_path, session_username)
    logger.info("Instagram session OK after probe (user %s)", session_username)
    return L


def test_session(
    session_path: Path | None = None,
    *,
    session_username: str = SESSION_USERNAME_DEFAULT,
    env_var: str = "INSTAGRAM_SESSION_B64",
    instagram_settings: dict | None = None,
) -> str | None:
    path = session_path or resolve_instagram_session_path(
        env_var=env_var, session_username=session_username
    )
    try:
        L = _bare_instaloader(None)
        _load_session_and_probe(
            L,
            path,
            session_username,
            instagram_settings if instagram_settings is not None else {},
        )
        return session_username
    except Exception:
        return None


def _instagram_login_retries_sec() -> list[float]:
    raw = os.environ.get("INSTAGRAM_LOGIN_RETRY_DELAYS_SEC", "").strip()
    if not raw:
        return [0.0, 240.0, 600.0, 960.0, 1500.0]
    delays: list[float] = []
    for part in raw.split(","):
        p = part.strip()
        if p:
            delays.append(max(0.0, float(p)))
    return delays or [0.0]


def ensure_instagram_session_ok(settings: dict) -> None:
    ig = settings.get("instagram") or {}
    session_username = str(ig.get("session_username", SESSION_USERNAME_DEFAULT))
    path = resolve_instagram_session_path(session_username=session_username)
    delays = _instagram_login_retries_sec()

    for i, pause in enumerate(delays):
        if pause > 0:
            logger.warning(
                "Instagram session probe retry in %.0fs (attempt %s/%s)",
                pause,
                i + 1,
                len(delays),
            )
            time.sleep(pause)
        try:
            L = _bare_instaloader(None)
            _load_session_and_probe(L, path, session_username, ig)
            _remember_verified_loader(L, path, session_username)
            logger.info("Instagram session probe OK (%s)", session_username)
            return
        except FileNotFoundError:
            raise
        except Exception as e:
            if _is_nonretryable_instagram(e):
                raise
            transient = _is_transient_instagram_failure(e)
            if i < len(delays) - 1 and transient:
                logger.warning("Instagram transient error — will retry: %s", e)
                continue
            raise
