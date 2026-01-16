from youtube_automation.ai.text.types import TextRequest
from youtube_automation.ai.text.providers.gemini import GeminiProvider


def test_text_provider_contract(mocker):
    mocker.patch.object(GeminiProvider, "generate", return_value="hello")

    p = GeminiProvider.__new__(GeminiProvider)
    out = p.generate(model="x", request=TextRequest(text="hi"))

    assert isinstance(out, str)
