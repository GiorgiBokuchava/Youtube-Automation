from typing import Optional
import time
import logging
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


class TextService:
    # Central AI service with smart model selection and fallback

    MAX_MODEL_TIME = 30  # Maximum time per model in seconds

    def __init__(self):
        self._providers: dict[str, object] = {
            "gemini": GeminiProvider(),
        }

        try:
            self._providers["openrouter"] = OpenRouterProvider()
        except Exception as e:
            logger.warning(f"OpenRouter disabled: {e}")

    def generate(
        self, request: TextRequest, preferred_model: Optional[str] = None
    ) -> str:
        # Generate response with automatic model selection and fallback

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
                        # Fall back to automatic selection

                    elapsed = time.time() - start
                    if elapsed > self.MAX_MODEL_TIME:
                        logger.debug(
                            "Preferred model %s exceeded %ss, skipping",
                            preferred_model,
                            self.MAX_MODEL_TIME,
                        )
                        # Fall back to automatic selection

                    if result:
                        return result

        # Get all models that support required capabilities
        suitable_models = get_models_by_capabilities(required_caps)

        if not suitable_models:
            raise ValueError(f"No models found for capabilities: {required_caps}")

        # Try models grouped by provider (exhaust all models in a provider before switching)
        last_error = None

        # Group models by provider
        provider_models = {}
        for model in suitable_models:
            provider_name = model["provider"]
            if provider_name not in provider_models:
                provider_models[provider_name] = []
            provider_models[provider_name].append(model)

        # Try each provider's models
        for provider_name, models in provider_models.items():
            provider = self._providers.get(provider_name)
            if not provider:
                continue

            for model in models:
                start = time.time()

                try:
                    result = provider.generate(model=model["model"], request=request)
                except Exception as e:
                    last_error = e
                    logger.debug("Model %s failed: %s", model["model"], e)
                    continue  # Try next model in same provider

                elapsed = time.time() - start
                if elapsed > self.MAX_MODEL_TIME:
                    logger.debug(
                        "Model %s exceeded %ss, skipping",
                        model["model"],
                        self.MAX_MODEL_TIME,
                    )
                    continue

                if result:
                    return result

        # If all models failed, raise the last error
        if last_error:
            raise RuntimeError(f"All models failed. Last error: {last_error}")
        else:
            raise RuntimeError("No suitable providers available")


# Global instance for easy access
text_service = TextService()
