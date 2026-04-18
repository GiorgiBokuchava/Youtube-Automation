from __future__ import annotations

import io
import random
import struct
import time
import wave
import logging
from typing import Optional, Union, List, Dict

logger = logging.getLogger(__name__)

from youtube_automation.ai.errors import (
    ModelTimeoutError,
    NoSuitableModelError,
    QuotaExhaustedError,
)
from youtube_automation.ai.tts.providers.edge import EdgeTTSProvider
from youtube_automation.ai.tts.providers.gemini import GeminiTTSProvider
from youtube_automation.ai.tts.providers.text_generator_io import (
    TextGeneratorTTSProvider,
)
from youtube_automation.ai.tts.registry import (
    get_models_by_capabilities,
    get_model_spec,
)
from youtube_automation.ai.tts.types import TTSRequest, TTSAudio


class TTSService:
    MAX_MODEL_TIME = 30

    def __init__(self) -> None:
        self._provider_factories: Dict[str, type] = {
            "gemini": GeminiTTSProvider,
            "text_generator": TextGeneratorTTSProvider,
            "edge": EdgeTTSProvider,
        }
        self._providers: Dict[str, object] = {}

    def _get_provider(self, name: str):
        if name not in self._providers:
            factory = self._provider_factories.get(name)
            if not factory:
                return None
            self._providers[name] = factory()
        return self._providers[name]

    def synthesize(
        self,
        request: TTSRequest,
        preferred_model: Optional[str] = None,
        tts_voices: Optional[Dict[str, Union[str, List[str]]]] = None,
    ) -> TTSAudio:
        required_caps = {"text_in", "audio_out"}

        gemini_error: Exception | None = None

        if preferred_model:
            spec = get_model_spec(preferred_model)
            if not spec:
                raise NoSuitableModelError(f"Unknown TTS model: {preferred_model}")

            provider = self._get_provider(spec["provider"])
            if not provider:
                raise NoSuitableModelError(f"No provider for {spec['provider']}")

            try:
                return self._try_one(
                    provider,
                    spec["provider"],
                    preferred_model,
                    request,
                    tts_voices,
                )
            except Exception as e:
                if spec["provider"] != "gemini":
                    raise
                gemini_error = e
                logger.debug(
                    "Preferred TTS provider %s failed: %s", spec["provider"], e
                )

        suitable = get_models_by_capabilities(required_caps)
        if not suitable:
            raise NoSuitableModelError("No TTS models available")

        provider_order = ["gemini", "text_generator", "edge"]
        last_error: Exception | None = gemini_error

        for provider_name in provider_order:
            provider = self._get_provider(provider_name)
            if not provider:
                continue

            for spec in suitable:
                if spec["provider"] != provider_name:
                    continue

                try:
                    return self._try_one(
                        provider,
                        provider_name,
                        spec["model"],
                        request,
                        tts_voices,
                    )
                except Exception as e:
                    last_error = e
                    logger.debug(
                        "TTS provider %s model %s failed: %s",
                        provider_name,
                        spec["model"],
                        e,
                    )
                    continue

        if isinstance(last_error, QuotaExhaustedError):
            raise last_error

        raise RuntimeError(
            f"All TTS providers failed. Last error: {last_error}"
        ) from last_error

    def _try_one(
        self,
        provider: object,
        provider_name: str,
        model_name: str,
        request: TTSRequest,
        tts_voices: Optional[Dict[str, Union[str, List[str]]]] = None,
    ) -> TTSAudio:
        start = time.time()

        voice = None
        if tts_voices and provider_name in tts_voices:
            voices_config = tts_voices[provider_name]
            # Handle both string (single voice) and list (multiple voices)
            if isinstance(voices_config, list):
                # Randomly select from available voices
                voice = random.choice(voices_config)
                logger.debug(
                    f"Randomly selected voice '{voice}' from {len(voices_config)} options for {provider_name}"
                )
            else:
                # Single voice (backward compatibility)
                voice = voices_config
                logger.debug(f"Using configured voice '{voice}' for {provider_name}")

        voice_request = TTSRequest(
            text=request.text,
            voice=voice,
            params=request.params,
        )

        data = provider.synthesize(model=model_name, request=voice_request)

        if time.time() - start > self.MAX_MODEL_TIME:
            raise ModelTimeoutError(f"{model_name} timed out")

        if provider_name == "gemini":
            if len(data) % 4 == 0:
                pcm16 = bytearray()
                for (sample,) in struct.iter_unpack("<f", data):
                    s = max(-1.0, min(1.0, sample))
                    pcm16.extend(struct.pack("<h", int(s * 32767)))
                pcm_bytes = bytes(pcm16)
            else:
                pcm_bytes = data

            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(pcm_bytes)

            audio_bytes = buf.getvalue()
            ext = ".wav"

        elif provider_name == "text_generator":
            audio_bytes = data
            ext = ".mp3"

        else:
            audio_bytes = data
            ext = ".mp3"

        out = TTSAudio(
            data=audio_bytes,
            ext=ext,
            provider=provider_name,
            model=model_name,
        )

        logger.debug(
            "TTS provider=%s model=%s ext=%s", out.provider, out.model, out.ext
        )
        return out


tts_service = TTSService()
