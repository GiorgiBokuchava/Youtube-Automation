from ast import List
import os
import base64
from openai import OpenAI

import requests
from youtube_automation.ai.text.types import TextRequest


def _encode_video(path) -> str:
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:video/mp4;base64,{b64}"


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self) -> None:
        keys_str = os.getenv("OPENROUTER_API_KEYS", "")
        if not keys_str:
            raise RuntimeError("OPENROUTER_API_KEYS is missing")

        # Split comma-separated keys and take first one
        keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        if not keys:
            raise RuntimeError("No valid OpenRouter API keys found")

        self._keys = keys
        self._current_key_index = 0

        self._client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=keys[0],
            timeout=10,
        )

    def generate(self, *, model: str, request: TextRequest) -> str:
        content = []

        if request.text:
            content.append({"type": "text", "text": request.text})

        if request.video:
            content.append(
                {
                    "type": "video_url",
                    "videoUrl": {"url": _encode_video(request.video)},
                }
            )

        # Try each key with fallback
        last_error = None
        for attempt in range(len(self._keys)):
            try:
                # Update client with current key
                self._client.api_key = self._keys[self._current_key_index]

                resp = self._client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": content}],
                    **request.params,
                )
                return (resp.choices[0].message.content or "").strip()

            except Exception as e:
                last_error = e
                self._current_key_index = (self._current_key_index + 1) % len(
                    self._keys
                )
                if attempt < len(self._keys) - 1:
                    continue  # Try next key
                raise e  # Re-raise if all keys failed


OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def fetch_free_openrouter_models() -> List[str]:
    api_key = os.getenv("OPENROUTER_API_KEYS")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEYS is missing")

    resp = requests.get(
        OPENROUTER_MODELS_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    resp.raise_for_status()

    models = resp.json()["data"]

    return [m["id"] for m in models if m["id"].endswith(":free")]
