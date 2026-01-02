import argparse

from src.youtube_automation.config.loader import load_env, load_settings
from src.youtube_automation.media import thumbnail
from src.youtube_automation.media.thumbnail import source_thumbnail
from src.youtube_automation.media.video import source_videos
from src.youtube_automation.storage.sessions import save_session, new_session


def main() -> None:
    load_env()
    settings = load_settings()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["videos", "thumbnail", "pipeline"],
        required=True,
    )
    parser.add_argument(
        "--debug",
        action="store_true",
    )
    args = parser.parse_args()

    if args.debug:
        thumbnail.DEBUG = True

    if args.mode == "thumbnail":
        thumb = source_thumbnail(settings)
        session = new_session(
            {
                "thumbnail": thumb or {},
                "clips": [],
                "num_clips": 0,
            }
        )
        save_session(session)
        print(thumb)
        return

    if args.mode == "videos":
        clips = source_videos(settings)
        session = new_session(
            {
                "clips": clips,
                "num_clips": len(clips),
            }
        )
        save_session(session)
        return

    clips = source_videos(settings)
    thumb = source_thumbnail(settings)

    session = new_session(
        {
            "clips": clips,
            "thumbnail": thumb or {},
            "num_clips": len(clips),
        }
    )
    save_session(session)


if __name__ == "__main__":
    main()
