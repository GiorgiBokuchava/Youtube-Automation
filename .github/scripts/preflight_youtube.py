"""GitHub Actions: validate YouTube OAuth refresh token for the selected channel."""

import os

from youtube_automation.config.loader import load_env
from youtube_automation.youtube.auth import ensure_youtube_refresh_token


def main() -> None:
    ch = os.environ.get("CHANNEL", "animals")
    load_env(ch)
    ensure_youtube_refresh_token()
    print(f"YouTube OAuth refresh OK for channel={ch}")


if __name__ == "__main__":
    main()
