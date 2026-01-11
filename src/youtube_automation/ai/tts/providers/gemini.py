import os

from youtube_automation.ai.tts.types import TTSRequest
from google import genai
from google.genai import types

from test import api_key


class GeminiTTSProvider:
    name = "gemini"

    def __init__(self) -> None:
        keys = os.getenv("GEMINI_API_KEYS")
        if not keys:
            raise ValueError("GEMINI_API_KEYS is not set")
        self._keys: list[str] = keys.split(",")

    def _is_quota_error(self, e: Exception) -> bool:
        msg = str(e).lower()
        return "429" in msg or "quota" in msg or "rate limit" in msg

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
                        **request.params,
                    ),
                )

                return response.candidates[0].content.parts[0].inline_data.data
            except Exception as e:
                last_error = e
                if self._is_quota_error(e):
                    continue
                raise
        raise RuntimeError("All Gemini API keys exhausted") from last_error
