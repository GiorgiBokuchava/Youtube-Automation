"""GitHub Actions helper: validate Instagram session path when sourcing is enabled."""

import os

from youtube_automation.config.loader import load_env, load_settings
from youtube_automation.instagram.client import resolve_instagram_session_path
from youtube_automation.sourcing import instagram_sourcing_enabled


def main() -> None:
    ch = os.environ.get("CHANNEL", "animals")
    load_env(ch)
    shorts_run = os.environ.get("APP_MODE") == "shorts"
    settings = load_settings(ch, shorts=shorts_run)
    if not instagram_sourcing_enabled(settings):
        return
    ig = settings.get("instagram") or {}
    u = str(ig.get("session_username", "instagram"))
    p = resolve_instagram_session_path(session_username=u)
    print(f"Instagram session pickle OK at {p} (probe runs once in pipeline step)")


if __name__ == "__main__":
    main()
