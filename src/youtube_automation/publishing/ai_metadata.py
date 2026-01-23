from __future__ import annotations

from typing import Dict, List

from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest
from youtube_automation.ai.text.registry import get_models_by_capabilities


SYSTEM_RULES = """
You are generating YouTube metadata.
Do NOT mention Reddit.
Do NOT mention AI.
Do NOT use emojis excessively (max 2).
Do NOT include hashtags inside description body.
Write natural, human-like marketing copy.
"""


def _build_prompt(
    *,
    clips: List[dict],
    tone: str,
    audience: str,
    call_to_action: str,
    max_hashtags: int,
) -> str:
    titles = [c.get("title", "") for c in clips if c.get("title")]
    subreddits = {c.get("subreddit") for c in clips if c.get("subreddit")}

    context = "\n".join(f"- {t}" for t in titles[:10])

    return f"""
{SYSTEM_RULES}

Generate YouTube metadata for a compilation video.

Tone: {tone}
Audience: {audience}

Source themes:
{subreddits}

Clip titles:
{context}

TASKS:
1. Generate ONE catchy YouTube title (max 90 characters).
2. Generate a compelling description (2–3 short paragraphs).
3. Add ONE clear call-to-action line ({call_to_action}).
4. Generate up to {max_hashtags} relevant hashtags (no emojis).

FORMAT STRICTLY AS:

TITLE:
<text>

DESCRIPTION:
<text>

HASHTAGS:
#tag1 #tag2 #tag3
""".strip()


def _pick_non_gemini_model() -> str:
    """
    Pick first available text-only model that is NOT Gemini.
    """
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
    tone = pub_cfg.get("tone", "fun")
    audience = pub_cfg.get("audience", "general viewers")
    call_to_action = pub_cfg.get("call_to_action", "subscribe")
    max_hashtags = int(pub_cfg.get("max_hashtags", 10))

    prompt = _build_prompt(
        clips=clips,
        tone=tone,
        audience=audience,
        call_to_action=call_to_action,
        max_hashtags=max_hashtags,
    )

    model = _pick_non_gemini_model()

    try:
        raw = text_service.generate(
            TextRequest(text=prompt),
            preferred_model=model,
        )

        parsed = _parse_response(raw)

        # Apply defensive fallbacks
        if not parsed.get("title"):
            parsed["title"] = settings.get("youtube", {}).get(
                "title_template", "Reddit Compilation"
            )

        if not parsed.get("description"):
            parsed["description"] = (
                settings.get("youtube", {})
                .get(
                    "description_template",
                    "Best clips from Reddit.\n\nCredits:\n{credits}",
                )
                .format(credits="")
            )

        # Enforce length limits
        if parsed.get("title"):
            parsed["title"] = parsed["title"][:90]

        if parsed.get("hashtags"):
            parsed["hashtags"] = parsed["hashtags"][:max_hashtags]

        return parsed

    except Exception as e:
        # Fallback to template-based metadata
        return {
            "title": settings.get("youtube", {}).get(
                "title_template", "Reddit Compilation"
            ),
            "description": settings.get("youtube", {})
            .get(
                "description_template", "Best clips from Reddit.\n\nCredits:\n{credits}"
            )
            .format(credits=""),
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

    hashtags = [h for h in hashtags if h.startswith("#")]

    return {
        "title": title.strip(),
        "description": description.strip(),
        "hashtags": hashtags,
    }
