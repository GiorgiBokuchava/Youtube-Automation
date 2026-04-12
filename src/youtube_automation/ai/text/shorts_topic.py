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
    search_query: str
    clip_count: int


def _parse_json_object(raw: str) -> dict:
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    return json.loads(raw)


def generate_shorts_topic(settings: dict) -> ShortsTopicPlan:
    """
    Ask the text model to pick one concrete topic from channel context so titles stay fresh.
    """
    sc = settings.get("shorts") or {}
    ch = settings.get("channel") or {}
    niche = str(ch.get("niche", "") or "").strip()
    seeds = sc.get("topic_seeds") or []
    if isinstance(seeds, str):
        seeds = [seeds]
    seeds_list = [str(s).strip() for s in seeds if str(s).strip()]

    mn = int(sc.get("clip_count_min", sc.get("clip_count", 5)))
    mx = int(sc.get("clip_count_max", sc.get("clip_count", 7)))
    mn = max(3, min(mn, 10))
    mx = max(mn, min(mx, 10))

    preferred = sc.get("preferred_topic_model")

    prompt = f"""You help plan a YouTube Shorts compilation for one channel.

Channel niche: {niche or "(not specified)"}
Optional seed phrases (use as inspiration only; you may pick something else on-theme): {seeds_list or "(none)"}

Choose ONE specific, searchable topic for a ranked list video titled like:
"Top N [topic] moments" (example style only — do not copy literally).

Rules:
- topic_title: 2–5 words, Title Case, good for an on-screen headline (no hashtags).
- search_query: 1–6 lowercase words to find matching Reddit video posts (no subreddit name, no quotes).
- clip_count: integer between {mn} and {mx} (how many ranked clips).

Respond with ONLY a JSON object and no other text:
{{"topic_title": "...", "search_query": "...", "clip_count": {mn}}}
"""

    try:
        raw = text_service.generate(TextRequest(text=prompt), preferred_model=preferred)
        data = _parse_json_object(raw)

        topic_title = str(data.get("topic_title", "")).strip()
        search_query = str(data.get("search_query", "")).strip().lower()
        count = int(data.get("clip_count", mn))

        if not topic_title or not search_query:
            raise ValueError("Shorts topic model returned empty topic_title or search_query")

        count = max(mn, min(mx, count))

        return ShortsTopicPlan(
            topic_title=topic_title,
            search_query=search_query,
            clip_count=count,
        )
    except Exception as e:
        if not seeds_list:
            raise RuntimeError(
                "Shorts topic AI failed and shorts.topic_seeds is empty; "
                "add topic_seeds in config/shorts/<channel>.yaml for fallback."
            ) from e
        picked = random.choice(seeds_list)
        logger.warning("Shorts topic AI failed (%s); using random seed %r", e, picked)
        return ShortsTopicPlan(
            topic_title=picked.title(),
            search_query=picked.lower(),
            clip_count=random.randint(mn, mx),
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
        search_query=plan.search_query,
        clip_count=n,
    )
