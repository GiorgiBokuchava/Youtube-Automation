import os

from google import genai
from google.genai import types

from youtube_automation.ai.tts.types import TTSRequest


class GeminiTTSProvider:
    name = "gemini"

    def __init__(self) -> None:
        keys = os.getenv("GEMINI_API_KEYS")
        if not keys:
            raise ValueError("GEMINI_API_KEYS is not set")
        self._keys: list[str] = [k.strip() for k in keys.split(",") if k.strip()]

    def _is_quota_error(self, e: Exception) -> bool:
        msg = str(e).lower()
        return (
            "429" in msg
            or "quota" in msg
            or "rate limit" in msg
            or "resource_exhausted" in msg
        )

    def synthesize(self, *, model: str, request: TTSRequest) -> bytes:
        last_error = None

        for key in self._keys:
            client = genai.Client(api_key=key)

            try:
                response = client.models.generate_content(
                    model=model,
                    contents=request.text,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=request.voice or "Kore",
                                )
                            )
                        ),
                    ),
                )

                part = response.candidates[0].content.parts[0]
                return part.inline_data.data

            except Exception as e:
                last_error = e

                msg = str(e).lower()
                if "not found" in msg or "not supported" in msg or "404" in msg:
                    continue

                if self._is_quota_error(e):
                    continue

                raise

        raise RuntimeError(
            "Gemini TTS unavailable, all keys/models failed"
        ) from last_error
