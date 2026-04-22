from youtube_automation.ai.tts.service import TTSService
from youtube_automation.ai.tts.types import TTSRequest


def test_tts_edge_used_when_gemini_fails(mocker, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "fake-key")

    mocker.patch(
        "youtube_automation.ai.tts.providers.gemini.GeminiTTSProvider.synthesize",
        side_effect=Exception("quota"),
    )
    mocker.patch(
        "youtube_automation.ai.tts.providers.edge.EdgeTTSProvider.synthesize",
        return_value=b"mp3data",
    )

    svc = TTSService()
    audio = svc.synthesize(TTSRequest(text="hello"))

    assert audio.data
    assert audio.provider == "edge"
