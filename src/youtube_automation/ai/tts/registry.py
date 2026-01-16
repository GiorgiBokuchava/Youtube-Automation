from typing import Literal, TypedDict


Capability = Literal["text_in", "audio_out"]


class TTSModelSpec(TypedDict):
    provider: str
    model: str
    capabilities: set[Capability]
    free: bool


TTS_MODELS: list[TTSModelSpec] = [
    {
        "provider": "gemini",
        "model": "gemini-2.5-flash-preview-tts",
        "capabilities": {"text_in", "audio_out"},
        "free": True,
    },
    {
        "provider": "edge",
        "model": "edge-tts",
        "capabilities": {"text_in", "audio_out"},
        "free": False,
    },
    {
        "provider": "text_generator",
        "model": "text-generator-tts",
        "capabilities": {"text_in", "audio_out"},
        "free": True,
    },
]


def get_models_by_capabilities(required: set[Capability]) -> list[TTSModelSpec]:
    return [model for model in TTS_MODELS if required.issubset(model["capabilities"])]


def get_models_by_provider(provider: str) -> list[TTSModelSpec]:
    return [model for model in TTS_MODELS if model["provider"] == provider]


def get_model_spec(model: str) -> TTSModelSpec | None:
    for spec in TTS_MODELS:
        if spec["model"] == model:
            return spec
    return None
