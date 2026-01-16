import os
from typing import List

from youtube_automation.ai.text.types import TextRequest
from youtube_automation.ai.errors import QuotaExhaustedError
from google import genai
from google.genai import types


class GeminiProvider:
    name = "gemini"

    def __init__(self) -> None:
        raw = os.getenv("GEMINI_API_KEYS", "")
        self._keys: List[str] = [k.strip() for k in raw.split(",") if k.strip()]

        if not self._keys:
            raise RuntimeError("GEMINI_API_KEYS is empty or missing")

    def get_available_models(self) -> list[str]:
        from youtube_automation.ai.text.registry import get_models_by_provider

        return [model["model"] for model in get_models_by_provider(self.name)]

    def supports_model(self, model: str) -> bool:
        return model in self.get_available_models()

    def _is_quota_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return (
            "429" in msg
            or "resource_exhausted" in msg
            or "quota" in msg
            or "rate limit" in msg
        )

    def generate(self, *, model: str, request: TextRequest) -> str:
        contents = []

        if request.video:
            contents.append(
                types.Part.from_bytes(
                    data=request.video.read_bytes(),
                    mime_type="video/mp4",
                )
            )

        if request.text:
            contents.append(request.text)

        if request.messages:
            contents.extend(request.messages)

        available_models = self.get_available_models()
        model_priority = [model] + [m for m in available_models if m != model]

        last_error = None

        for key in self._keys:
            client = genai.Client(api_key=key)

            for model_name in model_priority:
                try:
                    resp = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        **request.params,
                    )
                    return (resp.text or "").strip()

                except Exception as exc:
                    last_error = exc
                    if self._is_quota_error(exc):
                        continue
                    continue

            if last_error and not self._is_quota_error(last_error):
                continue

        raise QuotaExhaustedError("All Gemini models and API keys exhausted")
