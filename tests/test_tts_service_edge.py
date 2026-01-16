from pathlib import Path

from youtube_automation.ai.tts.service import tts_service
from youtube_automation.ai.tts.types import TTSRequest


def main():
    audio = tts_service.synthesize(
        TTSRequest(
            text="This is an Edge TTS service test.",
            voice="en-US-AvaMultilingualNeural",
        ),
        preferred_model="edge-tts",
    )

    out = Path("test_output/service_edge.mp3")
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(audio.data)

    print("Provider:", audio.provider)
    print("Model:", audio.model)
    print("Saved:", out)


if __name__ == "__main__":
    main()
