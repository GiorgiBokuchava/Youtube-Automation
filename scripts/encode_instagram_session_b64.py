#!/usr/bin/env python3
"""Build an Instaloader session pickle and print base64 for INSTAGRAM_SESSION_B64."""

from __future__ import annotations

import argparse
import base64
import http.cookiejar
import pickle
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youtube_automation.config.env_secrets import validate_instagram_session_bytes  # noqa: E402


def _cookies_from_netscape(path: Path) -> dict[str, str]:
    cj = http.cookiejar.MozillaCookieJar(str(path))
    cj.load(ignore_discard=True, ignore_expires=True)
    return {c.name: c.value for c in cj if "instagram" in c.domain.lower()}


def _session_bytes_from_cookies(cookies: dict[str, str]) -> bytes:
    data = pickle.dumps(cookies)
    validate_instagram_session_bytes(data)
    return data


def _session_bytes_from_pickle(path: Path) -> bytes:
    data = path.read_bytes()
    validate_instagram_session_bytes(data)
    return data


def _copy_text(text: str) -> None:
    if sys.platform == "win32":
        subprocess.run(["clip"], input=text, text=True, check=True)
        print("(copied to clipboard)", file=sys.stderr)
        return
    try:
        subprocess.run(["pbcopy"], input=text, text=True, check=True)
        print("(copied to clipboard)", file=sys.stderr)
    except FileNotFoundError:
        print("Clipboard not available — copy from stdout.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Output base64 for INSTAGRAM_SESSION_B64 (.env and GitHub Actions)."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--cookies",
        type=Path,
        help="Netscape cookie file exported while logged into instagram.com",
    )
    group.add_argument(
        "--pickle",
        type=Path,
        help="Existing Instaloader session pickle (one-off path; not stored in repo)",
    )
    parser.add_argument(
        "--env",
        action="store_true",
        help="Print INSTAGRAM_SESSION_B64=... line for .env",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy output to clipboard (Windows: clip; macOS: pbcopy)",
    )
    args = parser.parse_args()

    if args.cookies:
        if not args.cookies.is_file():
            raise SystemExit(f"Cookie file not found: {args.cookies}")
        cookies = _cookies_from_netscape(args.cookies)
        if not cookies.get("sessionid") or not cookies.get("csrftoken"):
            raise SystemExit(
                "Cookie file missing sessionid or csrftoken — export fresh Instagram cookies."
            )
        session_data = _session_bytes_from_cookies(cookies)
        print(f"# built from {len(cookies)} instagram cookies", file=sys.stderr)
    else:
        assert args.pickle is not None
        if not args.pickle.is_file():
            raise SystemExit(f"Pickle file not found: {args.pickle}")
        session_data = _session_bytes_from_pickle(args.pickle)
        print(f"# read {args.pickle} ({len(session_data)} bytes)", file=sys.stderr)

    b64 = base64.b64encode(session_data).decode("ascii")
    line = f"INSTAGRAM_SESSION_B64={b64}" if args.env else b64
    print(line)
    print(f"# {len(session_data)} byte pickle -> {len(b64)} char base64", file=sys.stderr)
    if args.copy:
        _copy_text(line)


if __name__ == "__main__":
    main()
