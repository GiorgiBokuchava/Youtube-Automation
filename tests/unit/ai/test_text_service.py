import os

from youtube_automation.ai.text.service import TextService
from youtube_automation.ai.text.types import TextRequest


def test_text_service_preferred_model_success(mocker):
    mocker.patch.dict("os.environ", {"GEMINI_API_KEYS": "test-key"}, clear=False)
    mocker.patch(
        "youtube_automation.ai.text.providers.gemini.GeminiProvider.generate",
        return_value="ok",
    )

    svc = TextService()
    res = svc.generate(TextRequest(text="hi"), preferred_model="gemini-2.5-flash")

    assert res == "ok"


def test_text_service_fallback_when_preferred_fails(mocker):
    mocker.patch.dict("os.environ", {"GEMINI_API_KEYS": "test-key"}, clear=False)
    mocker.patch(
        "youtube_automation.ai.text.providers.gemini.GeminiProvider.generate",
        side_effect=Exception("boom"),
    )
    mocker.patch(
        "youtube_automation.ai.text.service.get_models_by_capabilities",
        return_value=[
            {
                "provider": "openrouter",
                "model": "test:free",
                "capabilities": {"text_in", "text_out"},
                "free": True,
            },
        ],
    )

    svc = TextService()
    openrouter = mocker.Mock()
    openrouter.generate = mocker.Mock(return_value="fallback")
    svc._providers["openrouter"] = openrouter

    res = svc.generate(TextRequest(text="hi"), preferred_model="gemini-2.5-flash")

    assert res == "fallback"
    openrouter.generate.assert_called_once()


def test_text_service_omits_gemini_when_no_api_keys(mocker):
    mocker.patch.dict(os.environ, {"GEMINI_API_KEYS": ""}, clear=False)
    mocker.patch(
        "youtube_automation.ai.text.service.OpenRouterProvider",
        side_effect=RuntimeError("openrouter unavailable in test"),
    )

    svc = TextService()

    assert "gemini" not in svc._providers
