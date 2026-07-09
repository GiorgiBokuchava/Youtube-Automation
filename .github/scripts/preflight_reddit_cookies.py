"""GitHub Actions: yt-dlp probe using REDDIT_COOKIES from env (no on-disk secret file)."""

from __future__ import annotations

import os
import subprocess
import sys

from youtube_automation.config.env_secrets import get_reddit_cookies_path, read_b64_env
from youtube_automation.config.loader import load_env

DEFAULT_URL = "https://www.reddit.com/r/StartledCats/comments/17cn6g6/"


def main() -> None:
    load_env(os.environ.get("CHANNEL", "animals"))
    if not read_b64_env("REDDIT_COOKIES"):
        print("REDDIT_COOKIES unset — skipping yt-dlp cookie preflight")
        return

    path = get_reddit_cookies_path()
    if path is None:
        print("::error::REDDIT_COOKIES set but could not materialize cookie file")
        sys.exit(1)

    url = os.environ.get("REDDIT_PREFLIGHT_URL", DEFAULT_URL)
    print(f"Cookie preflight: {path} -> {url}")
    subprocess.run(
        ["yt-dlp", "--cookies", str(path), "--skip-download", url],
        check=True,
    )


if __name__ == "__main__":
    main()
