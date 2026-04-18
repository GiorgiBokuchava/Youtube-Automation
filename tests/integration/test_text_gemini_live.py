import pytest
from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest


@pytest.mark.integration
def test_gemini_text_live():
    text = text_service.generate(
        TextRequest(text="say hello"),
        preferred_model="gemini-2.5-flash",
    )
    assert text
