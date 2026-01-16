import argparse
import logging

from src.youtube_automation.config.loader import load_env, load_settings
from src.youtube_automation.media.thumbnail import source_thumbnail
from src.youtube_automation.media.video import source_videos
from src.youtube_automation.storage.sessions import save_session, new_session
from src.youtube_automation.pipeline import run_pipeline


def setup_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(message)s",
    )

    for noisy in ("urllib3", "praw", "prawcore", "requests", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    load_env()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["videos", "thumbnail", "pipeline"],
        required=True,
    )
    parser.add_argument(
        "--channel",
        required=True,
        help="Channel config name (animals, dashcam, etc.)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
    )
    args = parser.parse_args()

    settings = load_settings(args.channel)
    setup_logging(args.debug)

    if args.mode == "thumbnail":
        thumb = source_thumbnail(settings)
        session = new_session({"thumbnail": thumb or {}, "clips": [], "num_clips": 0})
        save_session(session, settings)
        print(thumb)
        return

    if args.mode == "videos":
        clips = source_videos(settings)
        session = new_session({"clips": clips, "num_clips": len(clips)})
        save_session(session, settings)
        print(f"Sourced {len(clips)} clips.")
        return

    session = run_pipeline(settings)
    print(f"Pipeline complete. Clips: {session.get('num_clips', 0)}")


if __name__ == "__main__":
    main()
