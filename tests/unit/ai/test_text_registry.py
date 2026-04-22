from youtube_automation.ai.text.registry import get_models_by_capabilities


def test_get_models_by_capability_text_only():
    models = get_models_by_capabilities({"text_in", "text_out"})
    assert models
    assert all("text_out" in m["capabilities"] for m in models)
