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


def _parse_json_object(raw: str) -> dict:
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    return json.loads(raw)


def generate_shorts_topic(settings: dict) -> ShortsTopicPlan:
    """
    Ask the text model to pick a creative niche topic based on the channel's general focus.
    """
    sc = settings.get("shorts") or {}
    ch = settings.get("channel") or {}
    niche = str(ch.get("niche", "animals")).strip()

    mn = int(sc.get("clip_count_min", sc.get("clip_count", 5)))
    mx = int(sc.get("clip_count_max", sc.get("clip_count", 7)))
    mn = max(3, min(mn, 10))
    mx = max(mn, min(mx, 10))

    preferred = sc.get("preferred_topic_model")

    prompt = f"""You are a viral YouTube Shorts content planner. 
I need a topic for a "Top X ... Moments" compilation video.

Channel Niche: {niche}

Your task:
1. Pick a highly specific, creative, and viral sub-niche or theme within '{niche}'. 
   DO NOT be generic (e.g., instead of "Dog", pick "Golden Retriever Zoomies" or "Husky Arguing").
2. Create a 2-4 word Title for this sub-niche (Title Case).
3. Create exactly 3 distinct search queries for Reddit, ranging from very specific to slightly broader.
   IMPORTANT: DO NOT include the word "reddit" in these queries.

Return ONLY a JSON object:
{{
  "topic_title": "The Title from Step 2",
  "search_queries": [
    "highly specific query", 
    "moderately specific query", 
    "broader related query"
  ],
  "clip_count": {random.randint(mn, mx)}
}}
"""

    try:
        raw = text_service.generate(TextRequest(text=prompt), preferred_model=preferred)
        data = _parse_json_object(raw)

        topic_title = str(data.get("topic_title", "")).strip()
        # Remove "Moments" if AI added it to avoid duplication in pipeline
        topic_title = re.sub(r"\s+Moments$", "", topic_title, flags=re.IGNORECASE)
        
        queries = data.get("search_queries", [])
        if not isinstance(queries, list):
            queries = [str(queries)]
        queries = [str(q).strip().lower() for q in queries if str(q).strip()]

        count = int(data.get("clip_count", mn))

        if not topic_title or not queries:
            raise ValueError("Shorts topic model returned empty results")

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
            "animals": ("Funny Animal", ["funny animal", "cute animal"]),
            "tech": ("Clever Hack", ["tech hack", "life hack"]),
            "gaming": ("Epic Win", ["gaming moment", "epic win"]),
        }
        topic, queries = fallbacks.get(niche.lower(), ("Interesting", ["interesting", "cool"]))
        return ShortsTopicPlan(
            topic_title=topic,
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
