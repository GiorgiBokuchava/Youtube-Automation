import pytest
from youtube_automation.ai.tts.service import tts_service
from youtube_automation.ai.tts.types import TTSRequest


@pytest.mark.integration
def test_edge_tts_live():
    audio = tts_service.synthesize(
        TTSRequest(text="hello"),
        preferred_model="edge-tts",
    )
    assert audio.data
