from typing import Set, TypedDict, Literal

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
    # OpenRouter: official free-model router
    {
        "provider": "openrouter",
        "model": "openrouter/free",
        "capabilities": {"text_in", "text_out"},
        "free": True,
    },
]


# Public helpers


def get_models_by_capabilities(
    required_capabilities: Set[Capability],
) -> list[TextModelSpec]:
    return [
        model
        for model in TEXT_MODELS
        if required_capabilities.issubset(model["capabilities"])
    ]


def get_models_by_provider(provider: str) -> list[TextModelSpec]:
    return [model for model in TEXT_MODELS if model["provider"] == provider]


def get_model_spec(model_name: str) -> TextModelSpec | None:
    for model in TEXT_MODELS:
        if model["model"] == model_name:
            return model
    return None
