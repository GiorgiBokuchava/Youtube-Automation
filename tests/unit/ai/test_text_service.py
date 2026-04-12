import youtube_automation.ai.text.registry as _registry
from youtube_automation.ai.text.service import TextService
from youtube_automation.ai.text.types import TextRequest


def test_text_service_preferred_model_success(mocker, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "fake-key")

    mocker.patch(
        "youtube_automation.ai.text.providers.gemini.GeminiProvider.generate",
        return_value="ok",
    )

    svc = TextService()
    res = svc.generate(TextRequest(text="hi"), preferred_model="gemini-2.5-flash")

    assert res == "ok"


def test_text_service_fallback_when_preferred_fails(mocker, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "fake-key")
    monkeypatch.setenv("OPENROUTER_API_KEYS", "fake-key")

    mocker.patch(
        "youtube_automation.ai.text.providers.gemini.GeminiProvider.generate",
        side_effect=Exception("boom"),
    )
    mocker.patch(
        "youtube_automation.ai.text.providers.openrouter.OpenRouterProvider.generate",
        return_value="fallback",
    )

    fake_or_model = {
        "provider": "openrouter",
        "model": "test/fake:free",
        "capabilities": {"text_in", "text_out"},
        "free": True,
    }
    orig_load = _registry._load_openrouter_free_models
    mocker.patch.object(
        _registry, "_load_openrouter_free_models", return_value=[fake_or_model]
    )
    _registry._OPENROUTER_MODELS = None

    try:
        svc = TextService()
        res = svc.generate(TextRequest(text="hi"), preferred_model="gemini-2.5-flash")
        assert res == "fallback"
    finally:
        _registry._OPENROUTER_MODELS = None
