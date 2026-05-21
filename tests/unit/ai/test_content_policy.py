from youtube_automation.ai.content_policy import (
    PG_AI_CONTENT_POLICY,
    apply_content_policy_to_prompt,
    is_pg_safe_text,
)
from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest


def test_apply_content_policy_prepends_safety_block():
    out = apply_content_policy_to_prompt("Write a title.")
    assert out.startswith(PG_AI_CONTENT_POLICY)
    assert "Write a title." in out


def test_policy_uses_categories_not_banned_word_lists():
    lower = PG_AI_CONTENT_POLICY.lower()
    assert "profanity" in lower
    assert "violence" in lower
    assert "dead" not in lower
    assert "killed" not in lower


def test_is_pg_safe_text_rejects_violent_words():
    assert not is_pg_safe_text("Three people dead after crash")
    assert is_pg_safe_text("Close call on the highway")


def test_text_service_injects_policy_into_prompt(mocker):
    captured: list[str] = []

    def fake_generate(*, model: str, request: TextRequest) -> str:
        captured.append(request.text or "")
        return "ok"

    mocker.patch(
        "youtube_automation.ai.text.registry.get_model_spec",
        return_value={"provider": "gemini", "capabilities": {"text_in", "text_out"}},
    )
    mocker.patch(
        "youtube_automation.ai.text.registry.get_models_by_capabilities",
        return_value=[],
    )
    mocker.patch.dict(
        text_service._providers,
        {"gemini": mocker.Mock(generate=fake_generate)},
    )

    text_service.generate(TextRequest(text="Task body"), preferred_model="gemini")

    assert captured
    assert PG_AI_CONTENT_POLICY in captured[0]
    assert "Task body" in captured[0]
