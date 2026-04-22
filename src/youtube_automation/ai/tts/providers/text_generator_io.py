import os
import requests

from youtube_automation.ai.tts.types import TTSRequest


class TextGeneratorTTSProvider:
    name = "text_generator"

    API_URL = "https://api.text-generator.io/api/v1/generate_speech"

    def __init__(self) -> None:
        self._secret = os.getenv("TEXT_GENERATOR_API_KEY") or ""

    def synthesize(self, *, model: str, request: TTSRequest) -> bytes:
        if not self._secret:
            raise RuntimeError("TEXT_GENERATOR_API_KEY missing")
        payload = {
            "text": request.text,
            "voice": request.voice or "af_sarah",
            "speed": request.params.get("speed", 1.0),
        }

        headers = {
            "Content-Type": "application/json",
            "secret": self._secret,
        }

        resp = requests.post(
            self.API_URL,
            headers=headers,
            json=payload,
            timeout=20,
        )

        if resp.status_code != 200:
            raise RuntimeError(
                f"text-generator TTS failed: {resp.status_code} {resp.text}"
            )

        return resp.content
