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
        # No keys is allowed at import/init time (tests, offline dev); generate() errors then.

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
        if not self._keys:
            raise QuotaExhaustedError("Gemini disabled (no API keys)")

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

        # Single attempt per model id: TextService walks the registry; do not fall
        # through to other models or retry keys here.
        client = genai.Client(api_key=self._keys[0])
        try:
            resp = client.models.generate_content(
                model=model,
                contents=contents,
                **request.params,
            )
            return (resp.text or "").strip()
        except Exception as exc:
            if self._is_quota_error(exc):
                raise QuotaExhaustedError(str(exc)) from exc
            raise
