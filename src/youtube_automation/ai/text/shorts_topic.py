"""Pick a niche topic + search query for Shorts using the shared text AI stack."""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass

from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShortsTopicPlan:
    topic_title: str
    search_queries: list[str]
    clip_count: int


def _cap_words(text: str, max_words: int) -> str:
    words = [w for w in (text or "").strip().split() if w]
    if max_words > 0 and len(words) > max_words:
        words = words[:max_words]
    return " ".join(words)


def sanitize_shorts_topic_title(title: str) -> str:
    """Fix frequent model typos before titles appear on-screen or in metadata."""
    t = (title or "").strip()
    if not t:
        return t
    fixes = (
        (r"\bAnimls\b", "Animals"),
        (r"\bAmimals\b", "Animals"),
        (r"\bAniamls\b", "Animals"),
    )
    for pat, repl in fixes:
        t = re.sub(pat, repl, t, flags=re.IGNORECASE)
    return t


def _hint_lines(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    s = str(raw).strip()
    return [s] if s else []


def _parse_json_object(raw: str) -> dict:
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    return json.loads(raw)


def build_shorts_topic_prompt(settings: dict) -> str:
    """Full prompt for Shorts topic + search queries (includes suggested clip_count)."""
    sc = settings.get("shorts") or {}
    ch = settings.get("channel") or {}
    niche = str(ch.get("niche", "animals")).strip()
    configured_count = sc.get("clip_count")
    randomize_count = bool(sc.get("randomize_clip_count", False))

    mn = int(sc.get("clip_count_min", sc.get("clip_count", 5)))
    mx = int(sc.get("clip_count_max", sc.get("clip_count", 5)))
    mn = max(3, min(mn, 10))
    mx = max(mn, min(mx, 10))

    fixed_count: int | None = None
    if configured_count is not None:
        fixed_count = max(3, min(int(configured_count), 10))
        if not randomize_count:
            mn = fixed_count
            mx = fixed_count

    title_max_words = int(sc.get("title_max_words", 10))
    topic_hints = _hint_lines(sc.get("topic_hints")) or _hint_lines(sc.get("topic_seeds"))
    search_query_hints = _hint_lines(sc.get("search_query_hints"))

    topic_hints_txt = "\n".join(f"- {h}" for h in topic_hints) if topic_hints else "(none — invent freely)"
    search_hints_txt = (
        "\n".join(f"- {h}" for h in search_query_hints)
        if search_query_hints
        else "(none — invent freely)"
    )

    return f"""You are a viral YouTube Shorts content planner.
Create a complete, natural-sounding Shorts title and Reddit search queries.

Channel niche: {niche}

Optional theme hints (examples only; do NOT copy verbatim — use as loose inspiration for tone/topic):
{topic_hints_txt}

Optional search-query style hints (examples only; do NOT copy or treat as final queries — you MUST still invent exactly 3 NEW queries tailored to this run and niche):
{search_hints_txt}

Your task:
1. Generate ONE complete compilation title (not a fragment). It must include the exact token "{{count}}" where the clip count belongs.
2. Keep the title <= {title_max_words} words.
3. Invent exactly 3 distinct Reddit search queries (specific → medium → slightly broader). Do not reuse the example hints as-is if any were given.
4. Do not include the word "reddit" in the queries.
5. Use correct English spelling everywhere (e.g. "Animals", not misspellings like "Animls").

Return ONLY a JSON object:
{{
  "topic_title": "Complete title with {{count}} token",
  "search_queries": [
    "your new specific query",
    "your new medium query",
    "your new broader query"
  ],
  "clip_count": {random.randint(mn, mx)}
}}
"""


def generate_shorts_topic(settings: dict) -> ShortsTopicPlan:
    """
    Ask the text model to pick a creative niche topic based on the channel's general focus.
    """
    sc = settings.get("shorts") or {}
    ch = settings.get("channel") or {}
    niche = str(ch.get("niche", "animals")).strip()
    configured_count = sc.get("clip_count")
    randomize_count = bool(sc.get("randomize_clip_count", False))

    mn = int(sc.get("clip_count_min", sc.get("clip_count", 5)))
    mx = int(sc.get("clip_count_max", sc.get("clip_count", 5)))
    mn = max(3, min(mn, 10))
    mx = max(mn, min(mx, 10))

    fixed_count: int | None = None
    if configured_count is not None:
        fixed_count = max(3, min(int(configured_count), 10))
        if not randomize_count:
            mn = fixed_count
            mx = fixed_count

    preferred = sc.get("preferred_topic_model")
    title_max_words = int(sc.get("title_max_words", 10))

    prompt = build_shorts_topic_prompt(settings)

    try:
        raw = text_service.generate(TextRequest(text=prompt), preferred_model=preferred)
        data = _parse_json_object(raw)

        topic_title = str(data.get("topic_title", "")).strip()
        topic_title = _cap_words(topic_title, title_max_words)
        topic_title = sanitize_shorts_topic_title(topic_title)

        queries = data.get("search_queries", [])
        if not isinstance(queries, list):
            queries = [str(queries)]
        queries = [str(q).strip().lower() for q in queries if str(q).strip()]

        count = int(data.get("clip_count", mn))

        if not topic_title or not queries:
            raise ValueError("Shorts topic model returned empty results")

        if fixed_count is not None and not randomize_count:
            count = fixed_count
        else:
            count = max(mn, min(mx, count))

        return ShortsTopicPlan(
            topic_title=topic_title,
            search_queries=queries,
            clip_count=count,
        )
    except Exception as e:
        logger.warning("Shorts topic AI failed (%s); using fallback", e)
        # Fallback to something matching the niche
        fallbacks = {
            "animals": ("Top {count} Funny Animal Moments", ["funny animal", "cute animal"]),
            "tech": ("Top {count} Clever Hack Moments", ["tech hack", "life hack"]),
            "gaming": ("Top {count} Epic Gaming Moments", ["gaming moment", "epic win"]),
        }
        nk = niche.lower()
        if nk in fallbacks:
            topic, queries = fallbacks[nk]
        elif "animal" in nk:
            topic, queries = fallbacks["animals"]
        elif "game" in nk:
            topic, queries = fallbacks["gaming"]
        else:
            topic, queries = ("Top {count} Wild Moments", ["interesting", "cool"])
        return ShortsTopicPlan(
            topic_title=sanitize_shorts_topic_title(topic),
            search_queries=queries,
            clip_count=6,
        )


def random_clip_count_if_needed(plan: ShortsTopicPlan, settings: dict) -> ShortsTopicPlan:
    """Optionally jitter clip count within YAML bounds (keeps runs varied)."""
    sc = settings.get("shorts") or {}
    if not sc.get("randomize_clip_count", False):
        return plan
    mn = int(sc.get("clip_count_min", plan.clip_count))
    mx = int(sc.get("clip_count_max", plan.clip_count))
    n = random.randint(max(3, mn), min(10, mx))
    return ShortsTopicPlan(
        topic_title=plan.topic_title,
        search_queries=plan.search_queries,
        clip_count=n,
    )
