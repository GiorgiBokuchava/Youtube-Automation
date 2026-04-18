from typing import Set, TypedDict, Literal
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
    return TEXT_MODELS + _load_openrouter_free_models()


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
