from pathlib import Path

from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest


def generate_video_commentary(video: Path) -> str:
    request = TextRequest(
        video=video,
        text=(
            "Generate a short, funny one-sentence commentary. "
            "Max 12 words. Casual tone. No emojis. No questions."
        ),
    )

    return text_service.generate(request)
