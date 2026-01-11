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
        key = os.getenv("OPENROUTER_API_KEYS")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEYS is missing")

        self._client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=key,
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

        resp = self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            **request.params,
        )

        return (resp.choices[0].message.content or "").strip()


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
