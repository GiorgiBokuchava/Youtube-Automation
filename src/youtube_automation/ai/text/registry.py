from typing import Set, TypedDict, Literal
import os
import requests

Capability = Literal[
    "text_in", "text_out", "image_in", "video_in", "audio_in", "tool_use"
]


class TextModelSpec(TypedDict):
    provider: str
    model: str
    capabilities: Set[Capability]
    free: bool


TEXT_MODELS: list[TextModelSpec] = [
    # Gemini: video-capable, ordered by quality then RPD headroom
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
        "model": "gemini-3-flash-preview",
        "capabilities": {"text_in", "text_out", "video_in"},
        "free": True,
    },
    {
        "provider": "gemini",
        "model": "gemini-3.1-flash-lite-preview",
        "capabilities": {"text_in", "text_out", "video_in"},
        "free": True,
    },
    {
        "provider": "gemini",
        "model": "gemini-robotics-er-1.5-preview",
        "capabilities": {"text_in", "text_out", "video_in"},
        "free": True,
    },
]


# Dynamic OpenRouter free models

_OPENROUTER_MODELS: list[TextModelSpec] | None = None


def _openrouter_capabilities(modalities: list[str]) -> Set[Capability]:
    caps: Set[Capability] = {"text_in", "text_out"}
    if "image" in modalities:
        caps.add("image_in")
    # video_in intentionally excluded: free-tier OpenRouter models do not accept
    # video file uploads — only Gemini handles that natively.
    if "audio" in modalities:
        caps.add("audio_in")
    return caps


def _load_openrouter_free_models() -> list[TextModelSpec]:
    global _OPENROUTER_MODELS
    if _OPENROUTER_MODELS is not None:
        return _OPENROUTER_MODELS

    api_key = os.getenv("OPENROUTER_API_KEYS")
    if not api_key:
        # Don't cache: load_env(channel) may not have run yet.
        return []

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
                "capabilities": _openrouter_capabilities(
                    m.get("architecture", {}).get("input_modalities") or []
                ),
                "free": True,
            }
            for m in models
            if m["id"].endswith(":free")
        ]

    except Exception as exc:
        print(f"[warn] OpenRouter model discovery failed: {exc}")
        _OPENROUTER_MODELS = []

    return _OPENROUTER_MODELS


# Dynamic NVIDIA NIM models

# Keywords in a model ID that signal it accepts image input
_NVIDIA_IMAGE_KEYWORDS = frozenset([
    "vision", "-vl", "vl-", "_vl_", "vila", "multimodal",
    "paligemma", "kosmos", "fuyu", "neva", "deplot",
    "pixtral", "llava", "molmo",
])

# VILA is a Video-Language model — it also accepts video frames
_NVIDIA_VIDEO_KEYWORDS = frozenset(["vila"])

# Model IDs containing any of these substrings are NOT chat/completion models
# (embeddings, reward, PII, parsing, CLIP, 3D-vision, etc.)
_NVIDIA_NON_CHAT = frozenset([
    "embed", "reward", "gliner", "parse", "nvclip",
    "streampetr", "rerank",
])


def _nvidia_capabilities(model_id: str) -> Set[Capability]:
    lower = model_id.lower()
    caps: Set[Capability] = {"text_in", "text_out"}

    if any(kw in lower for kw in _NVIDIA_IMAGE_KEYWORDS):
        caps.add("image_in")

    # video_in intentionally excluded: NVIDIA NIM does not accept video file uploads.
    # Video analysis is Gemini-only.

    return caps


def _is_nvidia_chat_model(model_id: str) -> bool:
    lower = model_id.lower()
    return not any(kw in lower for kw in _NVIDIA_NON_CHAT)


_NVIDIA_MODELS: list[TextModelSpec] | None = None


def _load_nvidia_models() -> list[TextModelSpec]:
    global _NVIDIA_MODELS
    if _NVIDIA_MODELS is not None:
        return _NVIDIA_MODELS

    api_key = os.getenv("NVIDIA_API_KEYS")
    if not api_key:
        # Don't cache: load_env(channel) may not have run yet.
        return []

    key = api_key.split(",")[0].strip()

    try:
        resp = requests.get(
            "https://integrate.api.nvidia.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        resp.raise_for_status()

        models = resp.json().get("data", [])

        _NVIDIA_MODELS = [
            {
                "provider": "nvidia",
                "model": m["id"],
                "capabilities": _nvidia_capabilities(m["id"]),
                "free": True,
            }
            for m in models
            if _is_nvidia_chat_model(m["id"])
        ]

    except Exception as exc:
        print(f"[warn] NVIDIA NIM model discovery failed: {exc}")
        _NVIDIA_MODELS = []

    return _NVIDIA_MODELS


def _all_models() -> list[TextModelSpec]:
    return TEXT_MODELS + _load_openrouter_free_models() + _load_nvidia_models()


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
