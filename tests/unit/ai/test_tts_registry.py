from youtube_automation.ai.tts.registry import get_models_by_capabilities


def test_tts_registry_audio_out():
    models = get_models_by_capabilities({"text_in", "audio_out"})
    assert models
