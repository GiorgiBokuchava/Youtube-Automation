from pathlib import Path
from dotenv import load_dotenv

from youtube_automation.ai.text.commentary import generate_video_commentary


def main() -> None:
    load_dotenv()

    video = Path("downloads") / "1q1k5zz.mp4"
    try:
        text = generate_video_commentary(video)
    except Exception as exc:
        # Surface provider / gateway errors clearly in the CLI output
        print("ERROR:", type(exc).__name__, "-", exc)
        raise

    if text:
        print("RESULT:", text)
    else:
        print("RESULT is empty (no commentary returned)")


if __name__ == "__main__":
    main()
