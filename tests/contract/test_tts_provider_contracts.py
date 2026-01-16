from youtube_automation.ai.tts.types import TTSAudio


def test_tts_audio_contract():
    a = TTSAudio(
        data=b"123",
        ext=".mp3",
        provider="edge",
        model="edge-tts",
    )

    assert a.ext.startswith(".")
    assert a.data
