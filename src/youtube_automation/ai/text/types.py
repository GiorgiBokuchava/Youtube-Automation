from __future__ import annotations
from pathlib import Path
from typing import Optional, Any, List

from youtube_automation.ai.text.registry import Capability


class TextRequest:
    def __init__(
        self,
        *,
        text: Optional[str] = None,
        video: Optional[Path] = None,
        images: Optional[List[Path]] = None,
        audio: Optional[Path] = None,
        messages: Optional[List[dict[str, Any]]] = None,
        params: Optional[dict[str, Any]] = None,
    ):
        self.text = text
        self.video = video
        self.images = images
        self.audio = audio
        self.messages = messages
        self.params = params or {}

    def get_required_capabilities(self) -> set[Capability]:
        caps: set[Capability] = set()

        if self.text or self.messages:
            caps.add("text_in")

        if self.video:
            caps.add("video_in")

        if self.images:
            caps.add("image_in")

        if self.audio:
            caps.add("audio_in")

        caps.add("text_out")

        return caps
