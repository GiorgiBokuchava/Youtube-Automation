import logging
import time
from typing import Optional

from youtube_automation.ai.text.registry import (
    get_models_by_capabilities,
    get_model_spec,
)
from youtube_automation.ai.text.providers.gemini import GeminiProvider
from youtube_automation.ai.text.providers.openrouter import OpenRouterProvider
from youtube_automation.ai.text.providers.nvidia import NvidiaProvider
from youtube_automation.ai.text.types import TextRequest

logger = logging.getLogger(__name__)


class TextService:
    MAX_MODEL_TIME = 30
    MAX_TOTAL_TIME = 90
    MAX_MODELS_PER_PROVIDER = 15

    def __init__(self):
        self._providers: dict[str, object] = {}

        try:
            self._providers["gemini"] = GeminiProvider()
        except Exception as e:
            logger.warning("Gemini disabled: %s", e)

        try:
            self._providers["openrouter"] = OpenRouterProvider()
        except Exception as e:
            logger.warning("OpenRouter disabled: %s", e)

        try:
            self._providers["nvidia"] = NvidiaProvider()
        except Exception as e:
            logger.warning("NVIDIA NIM disabled: %s", e)

    def generate(
        self, request: TextRequest, preferred_model: Optional[str] = None
    ) -> str:
        required_caps = request.get_required_capabilities()

        if preferred_model:
            model_spec = get_model_spec(preferred_model)
            if model_spec and required_caps.issubset(model_spec["capabilities"]):
                provider = self._providers.get(model_spec["provider"])
                if provider:
                    start = time.time()
                    result = None

                    try:
                        result = provider.generate(
                            model=preferred_model, request=request
                        )
                    except Exception as e:
                        logger.debug(
                            "Preferred model %s failed: %s", preferred_model, e
                        )

                    elapsed = time.time() - start
                    if elapsed > self.MAX_MODEL_TIME:
                        logger.debug(
                            "Preferred model %s exceeded %ss, skipping",
                            preferred_model,
                            self.MAX_MODEL_TIME,
                        )

                    if result:
                        return result

        suitable_models = get_models_by_capabilities(required_caps)

        if not suitable_models:
            raise ValueError(f"No models found for capabilities: {required_caps}")

        suitable_models = [
            m for m in suitable_models if self._providers.get(m["provider"])
        ]
        if not suitable_models:
            raise RuntimeError(
                f"No initialised providers available for capabilities: {required_caps}"
            )

        provider_models: dict[str, list] = {}
        for model in suitable_models:
            provider_name = model["provider"]
            if provider_name not in provider_models:
                provider_models[provider_name] = []
            provider_models[provider_name].append(model)

        last_error = None
        budget_start = time.time()

        for provider_name, models in provider_models.items():
            provider = self._providers.get(provider_name)
            if not provider:
                continue

            tried = 0
            for model in models:
                if tried >= self.MAX_MODELS_PER_PROVIDER:
                    logger.debug(
                        "Provider %s: reached model cap (%d), moving on",
                        provider_name,
                        self.MAX_MODELS_PER_PROVIDER,
                    )
                    break

                total_elapsed = time.time() - budget_start
                if total_elapsed > self.MAX_TOTAL_TIME:
                    logger.warning(
                        "TextService: exceeded %ss total budget "
                        "(provider=%s, tried=%d in this provider), giving up",
                        self.MAX_TOTAL_TIME,
                        provider_name,
                        tried,
                    )
                    raise RuntimeError(
                        f"All models failed within {self.MAX_TOTAL_TIME}s budget. "
                        f"Last error: {last_error}"
                    )

                tried += 1
                start = time.time()

                try:
                    result = provider.generate(model=model["model"], request=request)
                except Exception as e:
                    last_error = e
                    logger.debug("Model %s failed: %s", model["model"], e)
                    continue

                elapsed = time.time() - start
                if elapsed > self.MAX_MODEL_TIME:
                    logger.debug(
                        "Model %s took %.1fs (> %ss), skipping",
                        model["model"],
                        elapsed,
                        self.MAX_MODEL_TIME,
                    )
                    continue

                if result:
                    return result

        if last_error:
            raise RuntimeError(f"All models failed. Last error: {last_error}")
        raise RuntimeError("No suitable providers available")


text_service = TextService()
