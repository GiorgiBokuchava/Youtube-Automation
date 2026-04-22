from __future__ import annotations

from typing import Dict, List

from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest
from youtube_automation.ai.text.registry import get_models_by_capabilities


SYSTEM_RULES = """
You are generating YouTube metadata.

Rules:
- Do NOT mention Reddit.
- Do NOT mention AI or automation.
- Do NOT include hashtags inside the description body.
- Avoid generic titles like "Compilation", "Best Clips", or "Top Moments".
Write natural, human-sounding YouTube copy that matches the channel tone.
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

CLIP TITLES USED IN THIS VIDEO:
{clip_context}

Write YouTube metadata that matches the channel context above.

TITLE GUIDELINES:
- Be specific and descriptive
- Reflect the niche and tone accurately
- Focus on moments, ideas, or situations shown in the video
- Avoid generic phrasing (compilation, clips, top 10)
- Keep under 90 characters

TITLE EXAMPLES (adapt style, not content):
- When {ctx["niche"]} Take an Unexpected Turn
- Moments That Defined {ctx["niche"]}
- You Won’t Expect What Happens Next
- A Closer Look at {ctx["niche"]}

TASKS:
1. Write ONE YouTube title.
2. Write a description (2–3 short paragraphs).
3. Add ONE call to action: "{call_to_action}".
4. Add up to {max_hashtags} relevant hashtags.

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
    max_hashtags = int(pub_cfg.get("max_hashtags", 6))

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
            parsed["title"] = f"Moments from {ctx['niche']}"

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
            "title": f"Moments from {ctx['niche']}",
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
