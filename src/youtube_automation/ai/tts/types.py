from typing import Optional, Any


class TTSRequest:
    def __init__(
        self,
        *,
        text: str,
        voice: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ):
        if not text.strip():
            raise ValueError("TTS text must not be empty")

        self.text = text
        self.voice = voice
        self.params = params or {}
