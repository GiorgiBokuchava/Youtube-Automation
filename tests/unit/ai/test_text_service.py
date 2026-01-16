from youtube_automation.ai.text.service import TextService
from youtube_automation.ai.text.types import TextRequest


def test_text_service_preferred_model_success(mocker):
    mocker.patch(
        "youtube_automation.ai.text.providers.gemini.GeminiProvider.generate",
        return_value="ok",
    )

    svc = TextService()
    res = svc.generate(TextRequest(text="hi"), preferred_model="gemini-2.5-flash")

    assert res == "ok"


def test_text_service_fallback_when_preferred_fails(mocker):
    mocker.patch(
        "youtube_automation.ai.text.providers.gemini.GeminiProvider.generate",
        side_effect=Exception("boom"),
    )
    mocker.patch(
        "youtube_automation.ai.text.providers.openrouter.OpenRouterProvider.generate",
        return_value="fallback",
    )

    svc = TextService()
    res = svc.generate(TextRequest(text="hi"), preferred_model="gemini-2.5-flash")

    assert res == "fallback"
