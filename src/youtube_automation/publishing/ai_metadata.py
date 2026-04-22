from __future__ import annotations

from typing import Dict, List

from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest
from youtube_automation.ai.text.registry import get_models_by_capabilities


SYSTEM_RULES = """
You are writing YouTube metadata for a viral compilation channel run by a real creator.

Hard rules:
- Do NOT mention Reddit, AI, or automation.
- Do NOT use purple prose, thesaurus words, or AI-sounding filler language.
- Titles MUST include 1-2 relevant emojis and stay under 70 characters.
- Write like a real human creator: direct, punchy, authentic to the channel tone.
"""


# ---------------------------------------------------------------------------
# Tone-aware hints
# ---------------------------------------------------------------------------

_TONE_CONFIGS = {
    "fun": {
        "emojis": "😂 😹 🤣 💀 (pick 1-2 that match the specific content)",
        "desc_tone": "casual, funny",
        "banned": [
            "antics", "chaos makers", "wholesome moments", "furry roommates",
            "living their best life", "adorable", "delightful", "steal the spotlight",
        ],
        "patterns": [
            'These [X] Just [Did Y] 😂',
            'When [X] Completely Loses It 😂',
            '[X] Built Different 💀',
            'POV: [Relatable Funny Scenario] 😂',
            '[X] 😂 | [Short Punchy Phrase]',
        ],
    },
    "dramatic": {
        "emojis": "😳 😱 🚨 💥 ⚡ (pick 1-2 that match the specific content)",
        "desc_tone": "tense, gripping",
        "banned": [
            "heartwarming", "wholesome", "delightful", "adorable", "sweet",
            "brightens your day",
        ],
        "patterns": [
            'You Won\'t Believe What This [X] Did 😳',
            'When [X] Goes Horribly Wrong 😱',
            '[X] That Left Everyone Speechless 😳',
            'POV: You Just Witnessed [X] 😱',
            '[X] 🚨 | [Short Tense Phrase]',
        ],
    },
    "wholesome": {
        "emojis": "🥹 ❤️ 🥰 ✨ 💛 (pick 1-2 that match the specific content)",
        "desc_tone": "warm, genuine",
        "banned": [
            "heartwarming", "chaos makers", "hijinks", "furry roommates",
            "packed with", "living their best life",
        ],
        "patterns": [
            'These [X] Will Make Your Day ❤️',
            'When [X] Does [Something Sweet] 🥹',
            '[X] That Restored My Faith in Humanity ❤️',
            'POV: You Found [The Sweetest X] ✨',
            '[X] ❤️ | [Short Heartfelt Phrase]',
        ],
    },
    "educational": {
        "emojis": "🤯 💡 🔍 📌 (pick 1-2 that match the specific content)",
        "desc_tone": "informative, engaging",
        "banned": [
            "heartwarming", "wholesome", "delightful", "chaos makers", "adorable",
        ],
        "patterns": [
            'Most People Don\'t Know This About [X] 🤯',
            '[X] Explained in Under a Minute 💡',
            'Why [X] Always [Does Y] 🔍',
            'The Truth About [X] Nobody Talks About 📌',
            '[X] 🤯 | [Short Surprising Phrase]',
        ],
    },
}

_TONE_DEFAULT = {
    "emojis": "choose 1-2 emojis that naturally fit the content mood and niche",
    "desc_tone": "direct, engaging",
    "banned": [
        "heartwarming", "delightful", "wholesome moments", "chaos makers",
        "packed with", "living their best life",
    ],
    "patterns": [
        '[X] Just [Did Y] [emoji]',
        'When [X] [Action/Outcome] [emoji]',
        '[X] Built Different [emoji]',
        'POV: [Relatable Scenario] [emoji]',
        '[X] [emoji] | [Short Punchy Phrase]',
    ],
}


def _tone_hints(tone: str) -> dict:
    """Return tone-specific guidance for emoji choice, title patterns, and banned phrases."""
    return _TONE_CONFIGS.get(tone.lower().strip(), _TONE_DEFAULT)


# ---------------------------------------------------------------------------
# Channel context extraction
# ---------------------------------------------------------------------------

def _extract_channel_context(channel_cfg: dict) -> dict:
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


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(
    *,
    clips: List[dict],
    call_to_action: str,
    max_hashtags: int,
    channel_cfg: dict,
) -> str:
    ctx = _extract_channel_context(channel_cfg)
    niche = ctx["niche"]
    tone = ctx["tone"]
    audience = ctx["audience"]
    tags = ctx["tags"]

    hints = _tone_hints(tone)
    patterns_block = "\n".join(f'    "{p}"' for p in hints["patterns"])
    banned_block = ", ".join(f'"{p}"' for p in hints["banned"])

    titles = [c.get("title", "") for c in clips if c.get("title")]
    sources = sorted({c.get("subreddit") for c in clips if c.get("subreddit")})
    clip_context = "\n".join(f"- {t}" for t in titles[:12])

    subscribe_line = (
        call_to_action
        if call_to_action.lower() != "subscribe"
        else f"Subscribe for more {niche} videos every week!"
    )

    return f"""
{SYSTEM_RULES}

CHANNEL CONTEXT:
- Niche: {niche}
- Tone: {tone}
- Audience: {audience}
- Channel tags: {tags}
- Source subreddits: {sources}

CLIP TITLES FROM THIS VIDEO (use for flavour, not verbatim):
{clip_context}

---

TITLE RULES:
- Under 70 characters including emojis
- Include 1-2 emojis: {hints["emojis"]}
- Punchy, clickable — something a real person would stop scrolling for
- Use action verbs, strong words, numbers, or a first-person/POV setup
- Do NOT lead with: Compilation, Moments, Best Of, Top, Content
- Avoid these AI-sounding phrases: {banned_block}
- Good patterns for a {tone} {niche} channel:
{patterns_block}

DESCRIPTION RULES:
- Write 1-2 SHORT {hints["desc_tone"]} sentences about what is in the video (1-2 emojis inline)
- Immediately follow with this exact CTA block:

If you enjoyed the video:
👍 Like
💬 Comment your favorite clip
🔔 {subscribe_line}

All clips belong to their respective owners – I do not claim ownership. This channel is purely for entertainment purposes under fair use.

HASHTAG RULES:
- Write exactly {max_hashtags} hashtags on ONE line, space-separated
- Mix broad viral tags (#funny #viral #trending) with niche-specific tags for {niche}
- All lowercase, no spaces inside individual hashtags

---

FORMAT YOUR RESPONSE EXACTLY AS SHOWN (nothing outside these three sections):

TITLE:
<your title here>

DESCRIPTION:
<1-2 {hints["desc_tone"]} sentences with emojis>

If you enjoyed the video:
👍 Like
💬 Comment your favorite clip
🔔 {subscribe_line}

All clips belong to their respective owners – I do not claim ownership. This channel is purely for entertainment purposes under fair use.

HASHTAGS:
#tag1 #tag2 #tag3
""".strip()


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------

def _pick_metadata_model() -> str | None:
    """Pick a text model for metadata, preferring non-Gemini to avoid burning
    video-capable quota on a text-only task. Returns None if no models exist
    (text_service.generate will do its own fallback)."""
    models = get_models_by_capabilities({"text_in", "text_out"})
    non_gemini = [m for m in models if m["provider"] != "gemini"]
    if non_gemini:
        return non_gemini[0]["model"]
    if models:
        return models[0]["model"]
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_ai_metadata(
    *,
    settings: dict,
    clips: List[dict],
) -> Dict[str, object]:
    pub_cfg = settings.get("publishing", {}).get("ai_metadata", {})
    call_to_action = pub_cfg.get("call_to_action", "Subscribe for more.")
    max_hashtags = int(pub_cfg.get("max_hashtags", 15))

    prompt = _build_prompt(
        clips=clips,
        call_to_action=call_to_action,
        max_hashtags=max_hashtags,
        channel_cfg=settings,
    )

    model = _pick_metadata_model()

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
                f"Selected moments related to {ctx['niche']}.\n\n"
                f"{call_to_action}"
            ),
            "hashtags": [],
        }


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def _parse_response(text: str) -> Dict[str, object]:
    title = ""
    description = ""
    hashtags: List[str] = []

    section = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            if section == "description":
                description += "\n"
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
            section = None  # Only capture the first non-empty line after TITLE:
        elif section == "description":
            description += line + "\n"
        elif section == "hashtags":
            hashtags.extend(line.split())

    return {
        "title": title.strip(),
        "description": description.strip(),
        "hashtags": [h for h in hashtags if h.startswith("#")],
    }
