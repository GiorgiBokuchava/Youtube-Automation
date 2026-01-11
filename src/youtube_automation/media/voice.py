from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts

DEFAULT_VOICE = "en-US-BrianMultilingualNeural"


async def _tts_async(text: str, out_path: Path, voice: str) -> None:
    communicate = edge_tts.Communicate(text=text, voice=voice)
    await communicate.save(str(out_path))


def text_to_speech(text: str, out_path: Path, voice: str = DEFAULT_VOICE) -> None:
    if not text.strip():
        raise ValueError("Text must not be empty or whitespace")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    asyncio.run(_tts_async(text=text, out_path=out_path, voice=voice))
