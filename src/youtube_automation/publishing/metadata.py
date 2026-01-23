from datetime import date


def build_credits(clips: list[dict]) -> str:
    lines = []
    for clip in clips:
        if "permalink" in clip:
            lines.append(clip["permalink"])
    return "\n".join(lines)


def build_metadata(settings: dict, clips: list[dict]) -> dict:
    yt = settings["youtube"]
    credits = build_credits(clips)

    return {
        "title": yt["title_template"],
        "description": yt["description_template"].format(credits=credits),
        "tags": yt.get("tags", []),
        "category_id": yt.get("category_id", "15"),
        "privacy_status": yt.get("privacy_status", "public"),
    }
