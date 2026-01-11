import asyncio
import edge_tts
from youtube_automation.ai.tts.types import TTSRequest


DEFAULT_VOICE = "en-US-BrianMultilingualNeural"


class EdgeTTSProvider:
    name = "edge"

    async def _synthesize_async(self, request: TTSRequest) -> bytes:
        communicate = edge_tts.Communicate(
            text=request.text,
            voice=request.voice or DEFAULT_VOICE,
        )

        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])

        return b"".join(chunks)

    def synthesize(self, *, model: str, request: TTSRequest) -> bytes:
        return asyncio.run(self._synthesize_async(request))
