from typing import Optional
import logging
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

from youtube_automation.ai.text.registry import (
    get_models_by_capabilities,
    get_model_spec,
)
from youtube_automation.ai.text.providers.gemini import GeminiProvider
from youtube_automation.ai.text.providers.openrouter import OpenRouterProvider
from youtube_automation.ai.text.types import TextRequest


def _gemini_api_keys_configured() -> bool:
    raw = os.getenv("GEMINI_API_KEYS", "")
    return bool([k.strip() for k in raw.split(",") if k.strip()])


def _dedupe_models(models: list) -> list:
    seen: set[tuple[str, str]] = set()
    out = []
    for m in models:
        key = (m["provider"], m["model"])
        if key in seen:
            continue
        seen.add(key)
        out.append(m)
    return out


class TextService:
    # Central AI service with smart model selection and fallback

    def __init__(self):
        self._providers: dict[str, object] = {}

        if _gemini_api_keys_configured():
            self._providers["gemini"] = GeminiProvider()
        else:
            logger.info(
                "Gemini text provider skipped (no GEMINI_API_KEYS after channel env)"
            )

        try:
            self._providers["openrouter"] = OpenRouterProvider()
        except Exception as e:
            logger.warning(f"OpenRouter disabled: {e}")

    def generate(
        self, request: TextRequest, preferred_model: Optional[str] = None
    ) -> str:
        # Generate response with automatic model selection and fallback

        required_caps = request.get_required_capabilities()
        attempted: set[tuple[str, str]] = set()

        if preferred_model:
            model_spec = get_model_spec(preferred_model)
            if model_spec and required_caps.issubset(model_spec["capabilities"]):
                provider = self._providers.get(model_spec["provider"])
                if provider:
                    attempted.add((model_spec["provider"], preferred_model))
                    try:
                        result = provider.generate(
                            model=preferred_model, request=request
                        )
                        if result:
                            return result
                        logger.warning(
                            "Preferred model %s returned empty output",
                            preferred_model,
                        )
                    except Exception as e:
                        logger.warning(
                            "Preferred model %s failed: %s",
                            preferred_model,
                            e,
                            exc_info=True,
                        )

        # Get all models that support required capabilities (one attempt per model id)
        suitable_models = _dedupe_models(get_models_by_capabilities(required_caps))

        if not suitable_models:
            raise ValueError(f"No models found for capabilities: {required_caps}")

        last_error: Exception | None = None

        for model in suitable_models:
            key = (model["provider"], model["model"])
            if key in attempted:
                continue

            provider = self._providers.get(model["provider"])
            if not provider:
                continue

            attempted.add(key)

            try:
                result = provider.generate(model=model["model"], request=request)
            except Exception as e:
                last_error = e
                logger.warning(
                    "Model %s (%s) failed: %s",
                    model["model"],
                    model["provider"],
                    e,
                    exc_info=True,
                )
                continue

            if result:
                return result
            logger.warning(
                "Model %s (%s) returned empty output",
                model["model"],
                model["provider"],
            )

        # If all models failed, raise the last error
        if last_error:
            raise RuntimeError(
                f"All models failed. Last error: {last_error}"
            ) from last_error
        raise RuntimeError("No suitable providers available")


# Global instance for easy access
text_service = TextService()
