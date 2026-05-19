from __future__ import annotations

import base64
import logging
import os
import pickle
import time
from pathlib import Path

import instaloader
from instaloader.instaloader import (
    get_default_session_filename,
    get_legacy_session_filename,
)

from youtube_automation.config.loader import BASE_DIR

logger = logging.getLogger(__name__)

DEFAULT_SESSION_PROJECT = Path("sessions") / "instagram.session"
SESSION_USERNAME_DEFAULT = "instagram"

_SESSION_HELP = (
    "Instagram session (pickle from Instaloader’s ``save_session``): "
    "Browser login and Instaloader are different: CLI password login often returns "
    "``Unexpected null login result`` while instagram.com works. "
    "Workaround — ``pip install browser_cookie3`` (or ``pip install -e '.[instagram]'`` from the repo root), then "
    "``python -m instaloader --load-cookies edge`` (Firefox/Chrome use ``firefox`` / ``chrome``). "
    "Do not pass ``--login`` together with ``--load-cookies``; use the browser profile where you are already logged in. "
    "Firefox: with multiple profiles, Instaloader may read the wrong one — give ``--cookiefile`` "
    "(short ``-B``) path to that profile's ``cookies.sqlite`` (Firefox ``about:support`` shows “Profile Folder”). "
    "On success Instaloader saves ``session-<user>`` under its data directory. "
    "If you only see graphql 401 / ``wait a few minutes``, wait and retry, try another network; or set "
    "``INSTAGRAM_SKIP_TEST_LOGIN=1`` to skip the hashtag/profile session probe (downloads may still fail). "
    "When ``INSTAGRAM_SESSION_B64`` is set (e.g. CI), it is decoded and written to ``sessions/instagram.session`` "
    "on each run and takes precedence over any existing file there, unless "
    "``INSTAGRAM_PREFER_DISK_SESSION=1`` — then an existing validated on-disk session is used first. "
    "If Instagram returns ``checkpoint_required``, complete the in-app or web security challenge, then export a "
    "fresh session from a trusted network (home/mobile); datacenter IPs often trigger checkpoints. "
    "Without base64, session path order is: ``INSTAGRAM_SESSION_PATH``, ``sessions/instagram.session``, then "
    "``%LOCALAPPDATA%\\\\Instaloader\\\\session-<user>`` on Windows. "
    "YAML ``instagram.session_username`` must match the session’s account."
)


def _env_truthy_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def project_session_path() -> Path:
    """Copy Instaloader’s ``session-<user>`` here for a stable repo-local path."""
    return BASE_DIR / DEFAULT_SESSION_PROJECT


def _validate_instaloader_session_pickled_dict(path: Path) -> None:
    """
    Pickle matches ``requests.utils.dict_from_cookiejar``: flat str→str cookies.

    Instaloader loads with ``cookies.get_dict()['csrftoken']``.
    """
    try:
        data = pickle.loads(path.read_bytes())
    except Exception as exc:
        raise RuntimeError(
            f"Session pickle is unreadable: {exc}\n{_SESSION_HELP}"
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            f"Session pickle must be a dict (Instaloader cookie jar export), "
            f"got {type(data).__name__}.\n{_SESSION_HELP}"
        )

    csrftoken = data.get("csrftoken")
    sessionid = data.get("sessionid")
    if not str(csrftoken or "").strip():
        raise RuntimeError(
            "Invalid session pickle: missing or empty ``csrftoken``. "
            "Restore a fresh file from ``python -m instaloader --login YOUR_USER``. "
            f"{_SESSION_HELP}"
        )
    if not str(sessionid or "").strip():
        raise RuntimeError(
            "Invalid session pickle: empty ``sessionid``. "
            "Instagram may need cooldown or a fresh Instaloader login. "
            f"{_SESSION_HELP}"
        )


def _instagram_b64_from_env(env_var: str) -> str:
    raw = os.environ.get(env_var, "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        raw = raw[1:-1].strip()
    return "".join(raw.split())


def _decode_b64_session_bytes(b64: str) -> bytes:
    if not b64:
        raise RuntimeError(f"Empty session base64. {_SESSION_HELP}")
    errors: list[Exception] = []
    for validate in (True, False):
        try:
            return base64.b64decode(b64, validate=validate)
        except Exception as exc:
            errors.append(exc)
    raise RuntimeError(
        f"INSTAGRAM_SESSION_B64 is not valid base64 ({errors[-1]}). {_SESSION_HELP}"
    ) from errors[-1]


def decode_session(*, env_var: str = "INSTAGRAM_SESSION_B64") -> Path:
    """Decode B64 and write ``sessions/instagram.session`` (same as resolve when B64 is set)."""
    b64 = _instagram_b64_from_env(env_var)
    if not b64:
        raise RuntimeError(f"{env_var} is unset or empty. {_SESSION_HELP}")
    return _materialize_b64_to_project_session(b64)


def _materialize_b64_to_project_session(b64: str) -> Path:
    decoded = _decode_b64_session_bytes(b64)
    dest = project_session_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(decoded)
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    _validate_instaloader_session_pickled_dict(dest)
    logger.info(
        "Wrote Instaloader session to %s (%d bytes)",
        dest,
        len(decoded),
    )
    return dest


def _disk_candidates(username: str) -> list[Path]:
    paths: list[Path] = []
    custom = os.environ.get("INSTAGRAM_SESSION_PATH", "").strip()
    if custom:
        paths.append(Path(os.path.expandvars(os.path.expanduser(custom))))
    paths.append(project_session_path())
    paths.append(Path(get_default_session_filename(username)))
    paths.append(Path(get_legacy_session_filename(username)))
    paths.append(Path.cwd() / f"session-{username}")
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p.resolve()) if p.is_absolute() else str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def resolve_instagram_session_path(
    *,
    env_var: str = "INSTAGRAM_SESSION_B64",
    session_username: str | None = None,
) -> Path:
    """
    Path Instaloader can ``load_session_from_file`` from.

    **Precedence**: when ``INSTAGRAM_SESSION_B64`` is set, decode and write ``sessions/instagram.session``
    (overwriting any stale file), unless ``INSTAGRAM_PREFER_DISK_SESSION=1`` and a validated on-disk file exists first.
    Without base64: first validated path from ``INSTAGRAM_SESSION_PATH``, project ``sessions/instagram.session``,
    then Instaloader defaults.
    """
    b64 = _instagram_b64_from_env(env_var)
    uname = (session_username or SESSION_USERNAME_DEFAULT).strip() or SESSION_USERNAME_DEFAULT

    if b64 and _env_truthy_flag("INSTAGRAM_PREFER_DISK_SESSION"):
        for candidate in _disk_candidates(uname):
            if candidate.is_file():
                logger.info(
                    "Instagram: INSTAGRAM_PREFER_DISK_SESSION — using on-disk session %s (%d bytes) "
                    "(skipping %s overwrite)",
                    candidate,
                    candidate.stat().st_size,
                    env_var,
                )
                _validate_instaloader_session_pickled_dict(candidate)
                return candidate
        logger.warning(
            "Instagram: INSTAGRAM_PREFER_DISK_SESSION set but no valid on-disk session — falling back to %s",
            env_var,
        )

    if b64:
        logger.info(
            "Instagram: %s set — materializing session to %s (%d-char b64)",
            env_var,
            project_session_path(),
            len(b64),
        )
        return _materialize_b64_to_project_session(b64)

    for candidate in _disk_candidates(uname):
        if candidate.is_file():
            logger.info(
                "Instagram: using on-disk session file %s (%d bytes)",
                candidate,
                candidate.stat().st_size,
            )
            _validate_instaloader_session_pickled_dict(candidate)
            return candidate

    raise RuntimeError(
        "No Instagram session file found and "
        f"{env_var} is unset or empty. Checked: "
        + ", ".join(str(p) for p in _disk_candidates(uname))
        + f". {_SESSION_HELP}"
    )


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
                "Instagram 401 / wait — cool down and retry with a refreshed Instaloader session file "
                "or INSTAGRAM_SESSION_B64. From datacenter IPs (e.g. GitHub Actions) graphql may stay "
                "blocked; try refreshing the session from your home network, or set "
                "INSTAGRAM_SKIP_TEST_LOGIN=1 to skip the probe (downloads can still fail)."
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
