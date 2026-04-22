from pathlib import Path
from typing import List
import base64
import os
from openai import OpenAI

from youtube_automation.ai.text.types import TextRequest

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

_MIME_BY_SUFFIX = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}


def _encode_image(path: Path) -> str:
    mime = _MIME_BY_SUFFIX.get(path.suffix.lower(), "image/jpeg")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


class NvidiaProvider:
    name = "nvidia"

    def __init__(self) -> None:
        keys_str = os.getenv("NVIDIA_API_KEYS", "")
        if not keys_str:
            raise RuntimeError("NVIDIA_API_KEYS is missing")

        keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        if not keys:
            raise RuntimeError("No valid NVIDIA API keys found")

        self._keys = keys
        self._current_key_index = 0

        self._client = OpenAI(
            base_url=NVIDIA_BASE_URL,
            api_key=keys[0],
            timeout=30,
            max_retries=0,  # Provider handles key rotation; no SDK-level retries
        )

    def generate(self, *, model: str, request: TextRequest) -> str:
        content: list = []

        if request.text:
            content.append({"type": "text", "text": request.text})

        if request.images:
            for img_path in request.images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": _encode_image(img_path)},
                })

        last_error = None
        for attempt in range(len(self._keys)):
            try:
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
                    continue
                raise e


def fetch_nvidia_models(api_key: str) -> List[str]:
    import requests

    resp = requests.get(
        f"{NVIDIA_BASE_URL}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    resp.raise_for_status()
    return [m["id"] for m in resp.json().get("data", [])]
