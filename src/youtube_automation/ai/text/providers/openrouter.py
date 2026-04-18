from typing import List
import logging
import os
import base64
from openai import OpenAI

import requests
from youtube_automation.ai.text.types import TextRequest

logger = logging.getLogger(__name__)


def _encode_video(path) -> str:
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:video/mp4;base64,{b64}"


def _should_retry_with_next_openrouter_key(exc: Exception) -> bool:
    """Another comma-separated key may have its own OpenRouter / billing quota."""
    msg = str(exc).lower()
    if "temporarily rate-limited upstream" in msg:
        return False
    if "provider returned error" in msg and "upstream" in msg:
        return False
    if "402" in str(exc) and "spend" in msg:
        return True
    if "free-models-per-min" in msg or "free-models-per-day" in msg:
        return True
    if "rate limit exceeded" in msg and "upstream" not in msg:
        return True
    return False


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self) -> None:
        keys_str = os.getenv("OPENROUTER_API_KEYS", "")
        if not keys_str:
            raise RuntimeError("OPENROUTER_API_KEYS is missing")

        keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        if not keys:
            raise RuntimeError("No valid OpenRouter API keys found")

        self._keys = keys

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

        for idx, api_key in enumerate(self._keys):
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
                timeout=30,
                max_retries=0,
            )
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": content}],
                    **request.params,
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception as exc:
                if idx + 1 < len(self._keys) and _should_retry_with_next_openrouter_key(
                    exc
                ):
                    logger.warning(
                        "OpenRouter account-level limit on key %s/%s for model %s: %s; "
                        "trying next key",
                        idx + 1,
                        len(self._keys),
                        model,
                        exc,
                    )
                    continue
                raise


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
