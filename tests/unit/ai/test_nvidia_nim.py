"""
Integration tests for NVIDIA NIM provider.

These tests make real API calls and require NVIDIA_API_KEYS to be set.
They are skipped automatically when the key is absent.
"""

import os
from pathlib import Path
import pytest
from youtube_automation.config.loader import load_env

load_env("dashcam")

pytestmark = pytest.mark.skipif(
    not os.getenv("NVIDIA_API_KEYS"),
    reason="NVIDIA_API_KEYS not set",
)

# A local thumbnail used for image-to-text tests
_THUMBNAIL = Path(__file__).parents[3] / "thumbnails" / "dashcam_1sbasca_yt_auto.jpg"


def test_nvidia_list_models():
    """NVIDIA NIM /v1/models returns a non-empty list of raw model IDs."""
    from youtube_automation.ai.text.providers.nvidia import fetch_nvidia_models

    api_key = os.getenv("NVIDIA_API_KEYS", "").split(",")[0].strip()
    models = fetch_nvidia_models(api_key)

    assert isinstance(models, list)
    assert len(models) > 0
    assert all(isinstance(m, str) and m for m in models)


def test_nvidia_registry_chat_models_only():
    """Registry filters out non-chat models and tags capabilities correctly."""
    import youtube_automation.ai.text.registry as reg

    reg._NVIDIA_MODELS = None
    specs = reg._load_nvidia_models()
    reg._NVIDIA_MODELS = None

    ids = [s["model"] for s in specs]

    # Embedding, reward, and PII models must be excluded
    non_chat = [
        m for m in ids
        if any(kw in m.lower() for kw in ["embed", "reward", "gliner", "parse", "nvclip", "streampetr"])
    ]
    assert non_chat == [], f"Non-chat models slipped through: {non_chat}"

    # All remaining are marked free and have text caps
    assert all(s["free"] is True for s in specs)
    assert all("text_in" in s["capabilities"] for s in specs)
    assert all("text_out" in s["capabilities"] for s in specs)


def test_nvidia_registry_vision_models_tagged():
    """Vision models are tagged with image_in; VILA also gets video_in."""
    import youtube_automation.ai.text.registry as reg

    reg._NVIDIA_MODELS = None
    specs = reg._load_nvidia_models()
    reg._NVIDIA_MODELS = None

    by_id = {s["model"]: s for s in specs}

    # Llama vision models must carry image_in
    assert "meta/llama-3.2-11b-vision-instruct" in by_id
    assert "image_in" in by_id["meta/llama-3.2-11b-vision-instruct"]["capabilities"]

    # VILA is a video-language model — it has image_in but NVIDIA NIM does not
    # accept video file uploads, so video_in is intentionally not advertised.
    assert "nvidia/vila" in by_id
    assert "image_in" in by_id["nvidia/vila"]["capabilities"]
    assert "video_in" not in by_id["nvidia/vila"]["capabilities"]

    # Pure text models must NOT have image_in
    assert "text_in" in by_id["meta/llama-3.1-8b-instruct"]["capabilities"]
    assert "image_in" not in by_id["meta/llama-3.1-8b-instruct"]["capabilities"]


def test_nvidia_generate_text():
    """NvidiaProvider.generate returns a non-empty string for a simple prompt."""
    from youtube_automation.ai.text.providers.nvidia import NvidiaProvider
    from youtube_automation.ai.text.types import TextRequest

    provider = NvidiaProvider()
    result = provider.generate(
        model="meta/llama-3.1-8b-instruct",
        request=TextRequest(
            text="Reply with exactly the word: pong",
            params={"max_tokens": 16},
        ),
    )

    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.skipif(not _THUMBNAIL.exists(), reason="Test thumbnail not found")
def test_nvidia_image_to_text():
    """Vision model describes a real dashcam thumbnail image."""
    from youtube_automation.ai.text.providers.nvidia import NvidiaProvider
    from youtube_automation.ai.text.types import TextRequest

    provider = NvidiaProvider()
    result = provider.generate(
        model="meta/llama-3.2-11b-vision-instruct",
        request=TextRequest(
            text="Describe this image in one sentence.",
            images=[_THUMBNAIL],
            params={"max_tokens": 80},
        ),
    )

    assert isinstance(result, str)
    assert len(result) > 10
