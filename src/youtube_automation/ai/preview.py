"""
Preview YouTube AI metadata (title, description, hashtags) without sourcing or downloads.

Writes prompt, raw model text, and parsed output to out/<channel>/ai_preview/.
Console: errors, model trace, and output file path only.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from youtube_automation.config.loader import BASE_DIR
from youtube_automation.publishing.ai_metadata import (
    _extract_channel_context,
    build_metadata_prompt,
    generate_ai_metadata_traced,
)

_PROMPT_SOURCE = (
    "Prompt template: src/youtube_automation/publishing/ai_metadata.py "
    "(SYSTEM_RULES, _TONE_CONFIGS, _build_prompt)\n"
    "Channel overrides: config/channels/<channel>.yaml → publishing.ai_metadata "
    "(tone, audience, call_to_action, max_hashtags)\n"
    "Optional clip titles (only if you paste real sourced titles): "
    "publishing.ai_preview.sample_clips in channel YAML\n"
    "Base defaults: config/base.yaml → publishing.ai_metadata"
)


def _normalize_clip(raw: dict, index: int) -> dict:
    title = str(raw.get("title", "")).strip()
    if not title:
        raise ValueError(
            f"publishing.ai_preview.sample_clips[{index}] needs a non-empty title"
        )
    clip: dict = {"id": raw.get("id") or f"preview-{index + 1}", "title": title}
    if raw.get("subreddit"):
        clip["subreddit"] = str(raw["subreddit"]).strip()
    return clip


def clips_from_settings(settings: dict) -> list[dict]:
    """
    Clip dicts for the metadata prompt — only from ``publishing.ai_preview.sample_clips``.

    The real pipeline uses titles from sourced posts, not YAML. If ``sample_clips`` is
    omitted, preview runs with channel context only (empty clip-title block in prompt).
    """
    pub = settings.get("publishing") or {}
    preview_cfg = pub.get("ai_preview") or {}
    raw_clips = preview_cfg.get("sample_clips")

    if not raw_clips:
        return []

    if not isinstance(raw_clips, list):
        raise ValueError("publishing.ai_preview.sample_clips must be a list")
    return [_normalize_clip(c, i) for i, c in enumerate(raw_clips)]


def _preview_output_dir(settings: dict) -> Path:
    channel = (settings.get("channel") or {}).get("name") or "channel"
    return BASE_DIR / "out" / channel / "ai_preview"


def _format_output_file(
    *,
    settings: dict,
    clips: list[dict],
    prompt: str,
    raw: str,
    parsed: dict,
    trace_text: str,
    preferred_picked: str | None,
) -> str:
    ctx = _extract_channel_context(settings)
    pub = settings.get("publishing", {}).get("ai_metadata", {}) or {}
    hashtags = parsed.get("hashtags") or []
    parse_note = parsed.pop("_parse_note", None)

    lines = [
        f"# AI metadata preview — {datetime.now(timezone.utc).isoformat()}",
        "",
        _PROMPT_SOURCE,
        "",
        "## YAML settings used",
        f"channel.name: {(settings.get('channel') or {}).get('name')}",
        f"channel.niche: {ctx['niche']}",
        f"publishing.ai_metadata.tone: {pub.get('tone')}",
        f"publishing.ai_metadata.audience: {pub.get('audience')}",
        f"publishing.ai_metadata.call_to_action: {pub.get('call_to_action')}",
        f"publishing.ai_metadata.max_hashtags: {pub.get('max_hashtags')}",
        f"_pick_metadata_model() chose: {preferred_picked or '(registry fallback order)'}",
        "",
        "## Clip titles in prompt",
    ]
    if clips:
        for c in clips:
            sub = f" (r/{c['subreddit']})" if c.get("subreddit") else ""
            lines.append(f"- {c['title']}{sub}")
    else:
        lines.append(
            "(none — add publishing.ai_preview.sample_clips with real post titles "
            "from a sourced run, or run --mode videos first and copy titles in)"
        )

    lines.extend(
        [
            "",
            "## Full prompt sent to model",
            "",
            prompt,
            "",
            "------------------------------------------------",
            "",
            "## Raw model response",
            "",
            raw,
            "",
            "## Parsed output (what upload would use)",
            "",
            f"TITLE:\n{parsed.get('title', '')}",
            "",
            f"DESCRIPTION:\n{parsed.get('description', '')}",
            "",
            "HASHTAGS:",
            " ".join(hashtags) if hashtags else "(none parsed)",
            "",
            f"Parse check: {parse_note or 'ok'}",
            "",
            "## Model trace",
            "",
            trace_text,
            "",
        ]
    )
    return "\n".join(lines)


def _log_error(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def run_ai_metadata_preview(settings: dict) -> None:
    pub = settings.setdefault("publishing", {})
    pub.setdefault("ai_metadata", {})["enabled"] = True

    clips = clips_from_settings(settings)
    if not clips:
        print(
            "Note: no publishing.ai_preview.sample_clips — metadata prompt uses "
            "channel YAML only (no clip titles). Paste real sourced titles to match pipeline.",
            file=sys.stderr,
        )
    prompt = build_metadata_prompt(settings=settings, clips=clips)

    from youtube_automation.publishing.ai_metadata import _pick_metadata_model

    preferred_picked = _pick_metadata_model()
    out_dir = _preview_output_dir(settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stamped_path = out_dir / f"metadata_{stamp}.txt"
    latest_path = out_dir / "latest.txt"

    try:
        parsed, raw, trace = generate_ai_metadata_traced(settings=settings, clips=clips)
        body = _format_output_file(
            settings=settings,
            clips=clips,
            prompt=prompt,
            raw=raw,
            parsed=dict(parsed),
            trace_text=trace.format_console(),
            preferred_picked=preferred_picked,
        )
        stamped_path.write_text(body, encoding="utf-8")
        latest_path.write_text(body, encoding="utf-8")

        print(trace.format_console())
        print(f"Wrote: {latest_path}")
        print(f"Also:  {stamped_path}")

    except Exception as e:
        fail_body = "\n".join(
            [
                f"# AI metadata preview — FAILED — {datetime.now(timezone.utc).isoformat()}",
                "",
                _PROMPT_SOURCE,
                "",
                f"Error: {e}",
                "",
                traceback.format_exc(),
                "",
                "## Prompt (not sent or incomplete)",
                "",
                prompt,
            ]
        )
        stamped_path.write_text(fail_body, encoding="utf-8")
        latest_path.write_text(fail_body, encoding="utf-8")
        _log_error(str(e))
        print(traceback.format_exc(), file=sys.stderr)
        print(f"Details saved: {latest_path}", file=sys.stderr)
        print(_PROMPT_SOURCE, file=sys.stderr)
        raise SystemExit(1) from e


def run_ai_preview(settings: dict) -> None:
    run_ai_metadata_preview(settings)
