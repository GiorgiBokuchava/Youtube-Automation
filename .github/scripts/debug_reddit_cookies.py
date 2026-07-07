"""Safe Reddit cookie diagnostics for GitHub Actions (names only, no values)."""

from __future__ import annotations

import sys
from pathlib import Path

import os

from youtube_automation.config.env_secrets import get_reddit_cookies_path, read_b64_env
from youtube_automation.config.loader import load_env

NETSCAPE_HEADER = "# Netscape HTTP Cookie File"


def _cookie_names(path: Path) -> list[str]:
    names: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 6:
            names.append(parts[5])
    return names


def main() -> None:
    load_env(os.environ.get("CHANNEL", "animals"))
    if not read_b64_env("REDDIT_COOKIES"):
        print("REDDIT_COOKIES unset")
        sys.exit(0)

    path = get_reddit_cookies_path()
    if path is None:
        print("::error::REDDIT_COOKIES set but could not materialize cookie file")
        sys.exit(1)

    print(f"cookie_source=REDDIT_COOKIES")
    print(f"materialized_path={path}")
    print(f"exists={path.is_file()}")

    data = path.read_bytes()
    print(f"size_bytes={len(data)}")
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    print(f"line_count={len(lines)}")
    print(f"netscape_header={NETSCAPE_HEADER in text}")
    print(f"contains_reddit_domain={'reddit.com' in text.lower()}")

    names = _cookie_names(path)
    print(f"cookie_name_count={len(names)}")
    for name in sorted(set(names)):
        print(f"cookie_name={name}")


if __name__ == "__main__":
    main()
