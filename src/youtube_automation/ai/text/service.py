import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from youtube_automation.ai.text.registry import (
    get_models_by_capabilities,
    get_model_spec,
)
from youtube_automation.ai.text.providers.gemini import GeminiProvider
from youtube_automation.ai.text.providers.openrouter import OpenRouterProvider
from youtube_automation.ai.text.providers.nvidia import NvidiaProvider
from youtube_automation.ai.content_policy import apply_content_policy_to_prompt
from youtube_automation.ai.text.types import TextRequest

logger = logging.getLogger(__name__)


@dataclass
class ModelAttempt:
    model: str
    provider: str
    outcome: str
    detail: str = ""
    elapsed_sec: float | None = None


@dataclass
class TextGenerateTrace:
    preferred_model: str | None = None
    attempts: list[ModelAttempt] = field(default_factory=list)
    used_model: str | None = None
    raw_text: str | None = None

    def format_console(self) -> str:
        lines = []
        if self.preferred_model:
            lines.append(f"Preferred model: {self.preferred_model}")
        if not self.attempts:
            lines.append("(no model attempts recorded)")
        for a in self.attempts:
            bit = f"  [{a.outcome}] {a.provider}/{a.model}"
            if a.elapsed_sec is not None:
                bit += f" ({a.elapsed_sec:.1f}s)"
            if a.detail:
                bit += f" — {a.detail}"
            lines.append(bit)
        if self.used_model:
            lines.append(f"Used model: {self.used_model}")
        elif not self.raw_text:
            lines.append("Used model: (none — no successful response)")
        return "\n".join(lines)


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
        raw, _trace = self.generate_with_trace(request, preferred_model=preferred_model)
        return raw

    def generate_with_trace(
        self, request: TextRequest, preferred_model: Optional[str] = None
    ) -> tuple[str, TextGenerateTrace]:
        trace = TextGenerateTrace(preferred_model=preferred_model)
        if request.text:
            request.text = apply_content_policy_to_prompt(request.text)

        required_caps = request.get_required_capabilities()

        if preferred_model:
            model_spec = get_model_spec(preferred_model)
            if not model_spec:
                trace.attempts.append(
                    ModelAttempt(
                        model=preferred_model,
                        provider="?",
                        outcome="skipped",
                        detail="unknown model id in registry",
                    )
                )
            elif not required_caps.issubset(model_spec["capabilities"]):
                trace.attempts.append(
                    ModelAttempt(
                        model=preferred_model,
                        provider=model_spec["provider"],
                        outcome="skipped",
                        detail=f"missing capabilities {required_caps - model_spec['capabilities']}",
                    )
                )
            else:
                provider_name = model_spec["provider"]
                provider = self._providers.get(provider_name)
                if not provider:
                    trace.attempts.append(
                        ModelAttempt(
                            model=preferred_model,
                            provider=provider_name,
                            outcome="skipped",
                            detail="provider not initialised (check API keys)",
                        )
                    )
                else:
                    start = time.time()
                    result = None
                    err_msg = ""
                    try:
                        result = provider.generate(
                            model=preferred_model, request=request
                        )
                    except Exception as e:
                        err_msg = str(e)
                        logger.debug(
                            "Preferred model %s failed: %s", preferred_model, e
                        )

                    elapsed = time.time() - start
                    if err_msg:
                        trace.attempts.append(
                            ModelAttempt(
                                model=preferred_model,
                                provider=provider_name,
                                outcome="failed",
                                detail=err_msg,
                                elapsed_sec=elapsed,
                            )
                        )
                    elif elapsed > self.MAX_MODEL_TIME:
                        trace.attempts.append(
                            ModelAttempt(
                                model=preferred_model,
                                provider=provider_name,
                                outcome="skipped",
                                detail=f"exceeded {self.MAX_MODEL_TIME}s",
                                elapsed_sec=elapsed,
                            )
                        )
                    elif not result:
                        trace.attempts.append(
                            ModelAttempt(
                                model=preferred_model,
                                provider=provider_name,
                                outcome="skipped",
                                detail="empty response",
                                elapsed_sec=elapsed,
                            )
                        )
                    else:
                        trace.attempts.append(
                            ModelAttempt(
                                model=preferred_model,
                                provider=provider_name,
                                outcome="success",
                                elapsed_sec=elapsed,
                            )
                        )
                        trace.used_model = preferred_model
                        trace.raw_text = result
                        return result, trace

        suitable_models = get_models_by_capabilities(required_caps)

        if not suitable_models:
            raise ValueError(f"No models found for capabilities: {required_caps}")

        suitable_models = [
            m for m in suitable_models if self._providers.get(m["provider"])
        ]
        if not suitable_models:
            init = sorted(self._providers.keys())
            raise RuntimeError(
                f"No initialised providers available for capabilities: {required_caps}. "
                f"Active providers: {init or '(none — set API keys in .env)'}"
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
                    trace.attempts.append(
                        ModelAttempt(
                            model="(provider cap)",
                            provider=provider_name,
                            outcome="skipped",
                            detail=f"reached {self.MAX_MODELS_PER_PROVIDER} tries for provider",
                        )
                    )
                    break

                total_elapsed = time.time() - budget_start
                if total_elapsed > self.MAX_TOTAL_TIME:
                    raise RuntimeError(
                        f"All models failed within {self.MAX_TOTAL_TIME}s budget. "
                        f"Last error: {last_error}"
                    )

                tried += 1
                model_id = model["model"]
                start = time.time()
                err_msg = ""

                try:
                    result = provider.generate(model=model_id, request=request)
                except Exception as e:
                    last_error = e
                    err_msg = str(e)
                    logger.debug("Model %s failed: %s", model_id, e)
                    trace.attempts.append(
                        ModelAttempt(
                            model=model_id,
                            provider=provider_name,
                            outcome="failed",
                            detail=err_msg,
                            elapsed_sec=time.time() - start,
                        )
                    )
                    continue

                elapsed = time.time() - start
                if elapsed > self.MAX_MODEL_TIME:
                    trace.attempts.append(
                        ModelAttempt(
                            model=model_id,
                            provider=provider_name,
                            outcome="skipped",
                            detail=f"exceeded {self.MAX_MODEL_TIME}s",
                            elapsed_sec=elapsed,
                        )
                    )
                    continue

                if not result:
                    trace.attempts.append(
                        ModelAttempt(
                            model=model_id,
                            provider=provider_name,
                            outcome="skipped",
                            detail="empty response",
                            elapsed_sec=elapsed,
                        )
                    )
                    continue

                trace.attempts.append(
                    ModelAttempt(
                        model=model_id,
                        provider=provider_name,
                        outcome="success",
                        elapsed_sec=elapsed,
                    )
                )
                trace.used_model = model_id
                trace.raw_text = result
                return result, trace

        if last_error:
            raise RuntimeError(f"All models failed. Last error: {last_error}")
        raise RuntimeError("No suitable providers available")


text_service = TextService()
