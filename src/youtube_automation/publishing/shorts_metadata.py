"""Titles/descriptions/tags for Shorts uploads."""

from __future__ import annotations

import os

from youtube_automation.publishing.metadata import build_credits

_VALID_PRIVACY = frozenset({"public", "private", "unlisted"})


def build_shorts_metadata(settings: dict, main_title: str, clips: list[dict]) -> dict:
    yt = settings.get("youtube") or {}
    credits = build_credits(clips)

    title_tmpl = yt.get("shorts_title_template", "{main_title}")
    title = title_tmpl.format(main_title=main_title)

    desc_tmpl = yt.get(
        "shorts_description_template",
        "{main_title}\n\nCredits:\n{credits}",
    )
    description = desc_tmpl.format(main_title=main_title, credits=credits)

    if yt.get("shorts_tags") is not None:
        tags = list(yt.get("shorts_tags") or [])
    else:
        tags = list(yt.get("tags") or [])
    extra = yt.get("shorts_extra_tags") or []
    tags = list(dict.fromkeys(tags + list(extra)))

    privacy = yt.get("privacy_status", "public")
    env_privacy = os.environ.get("YT_PRIVACY", "").strip().lower()
    if env_privacy in _VALID_PRIVACY:
        privacy = env_privacy

    return {
        "title": title,
        "description": description,
        "tags": tags,
        "category_id": yt.get("category_id", "15"),
        "privacy_status": privacy,
    }
