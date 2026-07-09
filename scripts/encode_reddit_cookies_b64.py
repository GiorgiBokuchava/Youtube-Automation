#!/usr/bin/env python3
"""Print base64 for REDDIT_COOKIES (.env locally, GitHub Actions secret in CI)."""

from __future__ import annotations

import argparse
import base64
import subprocess
import sys
from pathlib import Path

NETSCAPE_HEADER = "# Netscape HTTP Cookie File"


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


def _validate_netscape(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if NETSCAPE_HEADER not in text and "reddit.com" not in text.lower():
        raise SystemExit(
            f"{path} does not look like a Netscape cookie export (missing header or reddit.com)."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Output base64 for REDDIT_COOKIES (.env and GitHub Actions)."
    )
    parser.add_argument(
        "--cookies",
        type=Path,
        required=True,
        help="Netscape cookie file exported while logged into reddit.com",
    )
    parser.add_argument(
        "--env",
        action="store_true",
        help="Print REDDIT_COOKIES=... line for .env",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy output to clipboard (Windows: clip; macOS: pbcopy)",
    )
    args = parser.parse_args()

    if not args.cookies.is_file():
        raise SystemExit(f"Cookie file not found: {args.cookies}")

    _validate_netscape(args.cookies)
    data = args.cookies.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    line = f"REDDIT_COOKIES={b64}" if args.env else b64
    print(line)
    print(f"# {len(data)} bytes -> {len(b64)} char base64", file=sys.stderr)
    if args.copy:
        _copy_text(line)


if __name__ == "__main__":
    main()
