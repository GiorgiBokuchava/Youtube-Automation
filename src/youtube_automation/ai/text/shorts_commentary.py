from __future__ import annotations
import logging
from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest

logger = logging.getLogger(__name__)

def generate_shorts_commentary(clip_title: str, topic: str) -> str:
    """
    Generate a very short (max 5 words) reaction/caption for a specific clip.
    """
    prompt = f"""Write a very short, funny/relevant reaction to this video.
Video Title: {clip_title}
Video Topic: {topic}

Rules:
- Length: 2 to 5 words EXACTLY.
- Tone: Casual/Funny.
- No hashtags, no emojis.
- Only the reaction text.

Example: "Wait for the end" or "Such a good boy" or "Pure chaos here".
"""
    try:
        req = TextRequest(text=prompt)
        # Use a fast model for short snippets
        result = text_service.generate(req).strip().strip('"').strip("'")
        
        # Enforce 8-word limit if AI is chatty
        words = result.split()
        if len(words) > 8:
            result = " ".join(words[:8])
            
        return result
    except Exception as e:
        logger.warning("Shorts commentary AI failed: %s", e)
        return "Wait for it..."


def generate_shorts_overlay_commentary(
    settings: dict,
    clip: dict,
    *,
    topic_title: str,
    video_main_title: str,
    segment_rank: int,
    total_segments: int,
) -> str:
    """Backward-compatible overlay caption generator for Shorts pipeline."""
    del settings, video_main_title, segment_rank, total_segments
    clip_title = str(clip.get("title", "") or "")
    return generate_shorts_commentary(clip_title=clip_title, topic=topic_title)
