from __future__ import annotations

from typing import Dict, List

from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest
from youtube_automation.ai.text.registry import get_models_by_capabilities


SYSTEM_RULES = """
You are writing YouTube metadata for a real channel.

Hard rules:
- Do NOT mention Reddit, AI, automation, or where the material came from.
- Do NOT invent details not supported by the clip titles.
- Do NOT include hashtags inside the description body.
- Keep everything human, clean, and publishable.

When clip titles are varied or thin on detail, write a strong broad title that fits the niche.
Do not force specificity when the input does not support it.
"""


def _extract_channel_context(channel_cfg: dict) -> dict:
    """
    Extracts dynamic channel context without assuming tone or genre.
    """
    channel = channel_cfg.get("channel", {})
    youtube = channel_cfg.get("youtube", {})
    publishing = channel_cfg.get("publishing", {}).get("ai_metadata", {})

    niche = (
        channel.get("niche")
        or channel.get("name")
        or ", ".join(youtube.get("tags", [])[:2])
        or "general content"
    )

    tone = publishing.get("tone", "neutral")
    audience = publishing.get("audience", "general viewers")

    return {
        "niche": niche,
        "tone": tone,
        "audience": audience,
        "tags": youtube.get("tags", []),
    }


def _build_prompt(
    *,
    clips: List[dict],
    call_to_action: str,
    max_hashtags: int,
    channel_cfg: dict,
) -> str:
    ctx = _extract_channel_context(channel_cfg)

    titles = [c.get("title", "") for c in clips if c.get("title")]
    sources = sorted({c.get("subreddit") for c in clips if c.get("subreddit")})

    clip_context = "\n".join(f"- {t}" for t in titles[:12])

    return f"""
{SYSTEM_RULES}

CHANNEL CONTEXT:
- Niche: {ctx["niche"]}
- Tone: {ctx["tone"]}
- Audience: {ctx["audience"]}
- Tags: {ctx["tags"]}
- Source themes: {sources}

CLIP TITLES:
{clip_context}

Use only the above to write the metadata. Do not assume access to footage.

TITLE:
- One title only, max 90 characters
- Should feel like a real YouTube upload from this channel
- Calibrate specificity to what the clip titles actually support — broad is fine when context is thin
- One emoji is allowed if it fits naturally; otherwise omit it

DESCRIPTION:
- Two short paragraphs
- Paragraph 1: what kind of moments or situations the viewer can expect, grounded in the clip titles
- Paragraph 2: natural viewer engagement; include this exact call to action once: "{call_to_action}"
- Do not repeat the title verbatim; do not overhype

HASHTAGS:
- Up to {max_hashtags}, but use fewer if only 2–3 are genuinely relevant
- Broad, searchable, evergreen — no subreddit-style or joke tags

FORMAT EXACTLY AS:

TITLE:
<text>

DESCRIPTION:
<text>

HASHTAGS:
#tag1 #tag2
""".strip()


def _pick_non_gemini_model() -> str:
    models = get_models_by_capabilities({"text_in", "text_out"})
    for m in models:
        if m["provider"] != "gemini":
            return m["model"]
    raise RuntimeError("No non-Gemini text models available")


def generate_ai_metadata(
    *,
    settings: dict,
    clips: List[dict],
) -> Dict[str, object]:
    pub_cfg = settings.get("publishing", {}).get("ai_metadata", {})
    call_to_action = pub_cfg.get("call_to_action", "Subscribe for more.")
    max_hashtags = int(pub_cfg.get("max_hashtags", 4))

    prompt = _build_prompt(
        clips=clips,
        call_to_action=call_to_action,
        max_hashtags=max_hashtags,
        channel_cfg=settings,
    )

    model = _pick_non_gemini_model()

    try:
        raw = text_service.generate(
            TextRequest(text=prompt),
            preferred_model=model,
        )

        parsed = _parse_response(raw)
        ctx = _extract_channel_context(settings)

        if not parsed.get("title"):
            parsed["title"] = f"Unexpected Moments in {ctx['niche']}"

        if not parsed.get("description"):
            parsed["description"] = (
                f"This video explores moments related to {ctx['niche']}.\n\n"
                f"{call_to_action}"
            )

        parsed["title"] = parsed["title"][:90]
        parsed["hashtags"] = parsed.get("hashtags", [])[:max_hashtags]

        return parsed

    except Exception:
        ctx = _extract_channel_context(settings)
        return {
            "title": f"Unexpected Moments in {ctx['niche']}",
            "description": (
                f"Selected moments related to {ctx['niche']}.\n\n" f"{call_to_action}"
            ),
            "hashtags": [],
        }


def _parse_response(text: str) -> Dict[str, object]:
    title = ""
    description = ""
    hashtags: List[str] = []

    section = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("TITLE:"):
            section = "title"
            continue
        if line.startswith("DESCRIPTION:"):
            section = "description"
            continue
        if line.startswith("HASHTAGS:"):
            section = "hashtags"
            continue

        if section == "title":
            title = line
        elif section == "description":
            description += line + "\n"
        elif section == "hashtags":
            hashtags.extend(line.split())

    return {
        "title": title.strip(),
        "description": description.strip(),
        "hashtags": [h for h in hashtags if h.startswith("#")],
    }
