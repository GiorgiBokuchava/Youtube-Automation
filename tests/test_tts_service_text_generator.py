from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from youtube_automation.ai.tts.service import tts_service
from youtube_automation.ai.tts.types import TTSRequest


def main():
    audio = tts_service.synthesize(
        TTSRequest(
            text="This is a text generator TTS service test.",
            voice="af_sarah",
        ),
        preferred_model="text-generator-tts",
    )

    out = Path("test_output/service_text_generator.mp3")
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(audio.data)

    print("Provider:", audio.provider)
    print("Model:", audio.model)
    print("Saved:", out)


if __name__ == "__main__":
    main()
