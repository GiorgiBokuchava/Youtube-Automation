import os

import pytest

from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest


@pytest.mark.integration
def test_gemini_text_live():
    if not (os.getenv("GEMINI_API_KEYS") or "").strip():
        pytest.skip("GEMINI_API_KEYS not set")
    text = text_service.generate(
        TextRequest(text="say hello"),
        preferred_model="gemini-2.5-flash",
    )
    assert text
