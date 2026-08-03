from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Set, Optional


def _used_path(settings: dict | None):
    if settings and "channel" in settings:
        name = settings["channel"]["name"]
        return Path(f"config/used_{name}.json")
    return Path("config/used.json")


def load_sessions(settings: Optional[dict] = None) -> List[dict]:
    used_path = _used_path(settings)
    if not used_path.exists():
        return []

    try:
        with open(used_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_session(session: dict, settings: Optional[dict] = None) -> None:
    # Add channel information to session if available
    if settings and "channel" in settings:
        session["channel"] = settings["channel"].get("name")

    sessions = load_sessions(settings)
    sessions.append(session)

    # Prune old sessions if settings provide horizon
    if settings:
        cutoff = _cutoff_from_settings(settings)
        if cutoff:
            sessions = [s for s in sessions if _is_session_after_cutoff(s, cutoff)]

    used_path = _used_path(settings)
    used_path.parent.mkdir(exist_ok=True)
    with open(used_path, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2)


def new_session(payload: dict) -> dict:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }


def _is_session_after_cutoff(session: dict, cutoff: datetime) -> bool:
    try:
        created = datetime.fromisoformat(session.get("created_at", ""))
        return created >= cutoff
    except Exception:
        return True


def _cutoff_from_settings(settings: dict) -> Optional[datetime]:
    horizon_days = settings.get("used_horizon_days", 0)

    if isinstance(horizon_days, int) and horizon_days > 0:
        return datetime.now(timezone.utc) - timedelta(days=horizon_days)

    return None


def get_used_video_ids(settings: dict) -> Set[str]:
    # Returns all video submission IDs that were already used, respecting `used_horizon_days` if configured.
    sessions = load_sessions(settings)
    used_ids: Set[str] = set()

    cutoff = _cutoff_from_settings(settings)
    channel_name = settings.get("channel", {}).get("name")

    for session in sessions:
        # Filter by channel if specified
        if channel_name and session.get("channel") != channel_name:
            continue

        if cutoff:
            try:
                created = datetime.fromisoformat(session.get("created_at", ""))
                if created < cutoff:
                    continue
            except Exception:
                pass

        for clip in session.get("clips", []):
            cid = clip.get("id")
            if cid:
                used_ids.add(cid)

    return used_ids


def get_used_thumbnail_ids(settings: Optional[dict] = None) -> Set[str]:
    sessions = load_sessions(settings)
    thumb_ids: Set[str] = set()

    channel_name = None
    cutoff = None
    if settings:
        channel_name = settings.get("channel", {}).get("name")
        cutoff = _cutoff_from_settings(settings)

    for session in sessions:
        if channel_name and session.get("channel") != channel_name:
            continue

        if cutoff:
            try:
                created = datetime.fromisoformat(session.get("created_at", ""))
                if created < cutoff:
                    continue
            except Exception:
                pass

        thumb = session.get("thumbnail", {})
        sid = thumb.get("submission_id")
        if sid:
            thumb_ids.add(sid)

    return thumb_ids
