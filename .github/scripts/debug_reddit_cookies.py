"""Safe Reddit cookie file diagnostics for GitHub Actions (names only, no values)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

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
    cookie_file = os.environ.get("REDDIT_COOKIES_FILE", "reddit_cookies.txt")
    path = Path(cookie_file)
    print(f"cookie_file={cookie_file}")
    print(f"exists={path.is_file()}")
    if not path.is_file():
        print("::error::Reddit cookie file missing after decode")
        sys.exit(1)

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
