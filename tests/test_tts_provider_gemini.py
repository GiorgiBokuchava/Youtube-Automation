from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from youtube_automation.ai.tts.service import tts_service
from youtube_automation.ai.tts.types import TTSRequest


def main():
    audio = tts_service.synthesize(
        TTSRequest(
            text="This is a Gemini TTS service test. It should sound natural.",
            voice="Kore",
        ),
        preferred_model="gemini-2.5-flash-preview-tts",
    )

    out = Path("test_output/service_gemini.wav")
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(audio.data)

    print("Provider:", audio.provider)
    print("Model:", audio.model)
    print("Saved:", out)


if __name__ == "__main__":
    main()
