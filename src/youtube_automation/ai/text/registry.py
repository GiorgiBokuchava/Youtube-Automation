from typing import Set, TypedDict, Literal, cast
import logging
import os
import requests

logger = logging.getLogger(__name__)

Capability = Literal[
    "text_in", "text_out", "image_in", "video_in", "audio_in", "tool_use"
]


class TextModelSpec(TypedDict):
    provider: str
    model: str
    capabilities: Set[Capability]
    free: bool


TEXT_MODELS: list[TextModelSpec] = [
    # Gemini: video-capable, primary
    {
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "capabilities": {"text_in", "text_out", "video_in"},
        "free": True,
    },
    {
        "provider": "gemini",
        "model": "gemini-2.5-flash-lite",
        "capabilities": {"text_in", "text_out", "video_in"},
        "free": True,
    },
    {
        "provider": "gemini",
        "model": "gemini-3-flash",
        "capabilities": {"text_in", "text_out", "video_in"},
        "free": True,
    },
    {
        "provider": "gemini",
        "model": "gemini-robotics-er-1.5-preview",
        "capabilities": {"text_in", "text_out", "video_in"},
        "free": True,
    },
    {
        "provider": "gemini",
        "model": "gemini-3-flash",
        "capabilities": {"text_in", "text_out"},
        "free": True,
    },
]


# Dynamic OpenRouter free models

_OPENROUTER_MODELS: list[TextModelSpec] | None = None

_NVIDIA_MODELS: list[TextModelSpec] | None = None

_NVIDIA_EXCLUDE_SUBSTR = (
    "embed",
    "reward",
    "gliner",
    "parse",
    "nvclip",
    "streampetr",
)


def _nvidia_capabilities_for_id(model_id: str) -> Set[Capability]:
    caps: Set[Capability] = {"text_in", "text_out"}
    low = model_id.lower()
    if "vila" in low or ("vision" in low and "llama" in low):
        caps.add("image_in")
    return caps


def _load_nvidia_models() -> list[TextModelSpec]:
    """Discover chat models from NVIDIA NIM; requires NVIDIA_API_KEYS when populated."""
    global _NVIDIA_MODELS
    if _NVIDIA_MODELS is not None:
        return _NVIDIA_MODELS

    from youtube_automation.ai.text.providers.nvidia import fetch_nvidia_models

    raw = os.getenv("NVIDIA_API_KEYS", "")
    if not raw:
        _NVIDIA_MODELS = []
        return _NVIDIA_MODELS

    api_key = raw.split(",")[0].strip()
    try:
        ids = fetch_nvidia_models(api_key)
    except Exception as exc:
        logger.warning("NVIDIA model discovery failed: %s", exc, exc_info=True)
        _NVIDIA_MODELS = []
        return _NVIDIA_MODELS

    out: list[TextModelSpec] = []
    for mid in ids:
        mlow = mid.lower()
        if any(s in mlow for s in _NVIDIA_EXCLUDE_SUBSTR):
            continue
        caps = _nvidia_capabilities_for_id(mid)
        out.append(
            cast(
                TextModelSpec,
                {
                    "provider": "nvidia",
                    "model": mid,
                    "capabilities": caps,
                    "free": True,
                },
            )
        )

    _NVIDIA_MODELS = out
    return _NVIDIA_MODELS


def _load_openrouter_free_models() -> list[TextModelSpec]:
    global _OPENROUTER_MODELS
    if _OPENROUTER_MODELS is not None:
        return _OPENROUTER_MODELS

    api_key = os.getenv("OPENROUTER_API_KEYS")
    if not api_key:
        _OPENROUTER_MODELS = []
        return _OPENROUTER_MODELS

    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()

        models = resp.json()["data"]

        _OPENROUTER_MODELS = [
            {
                "provider": "openrouter",
                "model": m["id"],
                "capabilities": {"text_in", "text_out"},
                "free": True,
            }
            for m in models
            if m["id"].endswith(":free")
        ]

    except Exception as exc:
        logger.warning("OpenRouter model discovery failed: %s", exc, exc_info=True)
        _OPENROUTER_MODELS = []

    return _OPENROUTER_MODELS


def _all_models() -> list[TextModelSpec]:
    return (
        TEXT_MODELS + _load_openrouter_free_models() + _load_nvidia_models()
    )


# Public helpers


def get_models_by_capabilities(
    required_capabilities: Set[Capability],
) -> list[TextModelSpec]:
    return [
        model
        for model in _all_models()
        if required_capabilities.issubset(model["capabilities"])
    ]


def get_models_by_provider(provider: str) -> list[TextModelSpec]:
    return [model for model in _all_models() if model["provider"] == provider]


def get_model_spec(model_name: str) -> TextModelSpec | None:
    for model in _all_models():
        if model["model"] == model_name:
            return model
    return None
