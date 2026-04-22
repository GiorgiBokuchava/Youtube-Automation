import pytest

from youtube_automation.ai.text.providers.openrouter import (
    OpenRouterProvider,
    _should_retry_with_next_openrouter_key,
)
from youtube_automation.ai.text.types import TextRequest


@pytest.mark.parametrize(
    ("msg", "expected"),
    [
        ("Error code: 429 - free-models-per-min", True),
        ("Error code: 429 - free-models-per-day", True),
        ("Rate limit exceeded: free-models-per-min. ", True),
        (
            "429 Provider returned error qwen temporarily rate-limited upstream",
            False,
        ),
        ("temporarily rate-limited upstream", False),
        (
            "402 - spend limit exceeded",
            True,
        ),
        ("some random error", False),
    ],
)
def test_should_retry_with_next_key_heuristic(msg, expected):
    exc = Exception(msg)
    assert _should_retry_with_next_openrouter_key(exc) is expected


def test_openrouter_tries_second_key_on_account_limit(mocker):
    mocker.patch.dict(
        "os.environ",
        {"OPENROUTER_API_KEYS": "key-a,key-b"},
        clear=False,
    )

    create = mocker.patch(
        "youtube_automation.ai.text.providers.openrouter.OpenAI"
    ).return_value.chat.completions.create
    create.side_effect = [
        Exception("Error code: 429 - free-models-per-min"),
        mocker.Mock(choices=[mocker.Mock(message=mocker.Mock(content=" ok "))]),
    ]

    p = OpenRouterProvider()
    out = p.generate(model="x:free", request=TextRequest(text="hi"))

    assert out == "ok"
    assert create.call_count == 2
