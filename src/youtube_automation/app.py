import argparse
import logging
import sys

from youtube_automation.config.loader import load_env, load_settings
from youtube_automation.pipeline import NoClipsSourcedError, run_pipeline
from youtube_automation.media.thumbnail import source_thumbnail
from youtube_automation.instagram.client import ensure_instagram_session_ok
from youtube_automation.sourcing import instagram_sourcing_enabled, source_all_videos
from youtube_automation.storage.sessions import save_session, new_session


def setup_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(message)s",
    )

    for noisy in (
        "urllib3",
        "praw",
        "prawcore",
        "requests",
        "httpx",
        "httpcore",
        "instaloader",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip YouTube upload (for testing)",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help=(
            "After a full successful run only, delete generated media (voiceovers, renders, "
            "normalized clips, outputs, thumbnail cache, downloads). Skipped if the "
            "pipeline aborts so you can inspect intermediates. When omitted, files stay "
            "under out/<channel>/."
        ),
    )
    parser.add_argument(
        "--target-duration-minutes",
        type=float,
        default=None,
        help=(
            "Optional override for final_target_duration from YAML. "
            "Useful for fast dry-run tests."
        ),
    )
    parser.add_argument(
        "--no-commentary",
        action="store_true",
        help="Disable AI commentary and TTS for this run.",
    )
    parser.add_argument(
        "--no-music",
        action="store_true",
        help="Disable background music mix for this run.",
    )
    parser.add_argument(
        "--no-ai-metadata",
        action="store_true",
        help="Disable AI-generated title/description/hashtags for this run.",
    )
    parser.add_argument(
        "--core-only",
        action="store_true",
        help="Disable commentary and music (AI metadata still runs).",
    )
    _source = parser.add_mutually_exclusive_group()
    _source.add_argument(
        "--instagram-only",
        action="store_true",
        help=(
            "Source clips from Instagram only (skip Reddit). Requires instagram.hashtags "
            "in the channel YAML and a valid session (INSTAGRAM_SESSION_B64 or sessions/instagram.session)."
        ),
    )
    _source.add_argument(
        "--reddit-only",
        action="store_true",
        help="Source clips from Reddit only (skip Instagram). Requires non-empty subreddits in the channel YAML.",
    )
    args = parser.parse_args()

    load_env(args.channel)
    setup_logging(args.debug)

    logger = logging.getLogger(__name__)
    settings = load_settings(args.channel)

    if args.no_commentary or args.core_only:
        settings.setdefault("commentary", {})["every_nth"] = 0

    if args.no_music or args.core_only:
        settings.setdefault("music", {})["enabled"] = False

    if args.no_ai_metadata:
        settings.setdefault("publishing", {}).setdefault("ai_metadata", {})[
            "enabled"
        ] = False

    if args.target_duration_minutes is not None:
        if args.target_duration_minutes <= 0:
            raise ValueError("--target-duration-minutes must be > 0")
        settings["final_target_duration"] = float(args.target_duration_minutes)

    if args.instagram_only:
        ig = settings.get("instagram") or {}
        tags = [h for h in (ig.get("hashtags") or []) if str(h).strip()]
        if not tags:
            raise ValueError(
                "--instagram-only requires non-empty instagram.hashtags in the channel YAML."
            )
        settings["source_split"] = {"reddit": 0.0, "instagram": 1.0}
    elif args.reddit_only:
        subs = [s for s in (settings.get("subreddits") or []) if str(s).strip()]
        if not subs:
            raise ValueError(
                "--reddit-only requires non-empty subreddits in the channel YAML."
            )
        settings["source_split"] = {"reddit": 1.0, "instagram": 0.0}

    target_dur = settings.get("final_target_duration")
    every_n = settings.get("commentary", {}).get("every_nth", 3)
    music_on = settings.get("music", {}).get("enabled", True)
    ai_meta_on = settings.get("publishing", {}).get("ai_metadata", {}).get("enabled", False)

    logger.info(
        "Channel: %s | Mode: %s | Target: %s min | Commentary: %s | Music: %s | AI metadata: %s | Sourcing: %s",
        args.channel,
        args.mode,
        target_dur,
        f"every {every_n}" if every_n and every_n > 0 else "off",
        "on" if music_on else "off",
        "on" if ai_meta_on else "off",
        (
            "instagram only"
            if args.instagram_only
            else ("reddit only" if args.reddit_only else "yaml (reddit + instagram split)")
        ),
    )

    if args.mode == "thumbnail":
        thumb = source_thumbnail(settings)
        session = new_session({"thumbnail": thumb or {}, "clips": [], "num_clips": 0})
        save_session(session, settings)
        print(thumb)
        return

    if args.mode == "videos":
        if instagram_sourcing_enabled(settings):
            ensure_instagram_session_ok(settings)
        clips = source_all_videos(settings)
        session = new_session({"clips": clips, "num_clips": len(clips)})
        save_session(session, settings)
        print(f"Sourced {len(clips)} clips.")
        return

    try:
        session = run_pipeline(settings, dry_run=args.dry_run, cleanup=args.cleanup)
    except NoClipsSourcedError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    print(f"Pipeline complete. Clips: {session.get('num_clips', 0)}")
    errs = session.get("pipeline_errors") or []
    if errs:
        print(f"Warnings: {len(errs)} pipeline step(s) logged issues (see logs).")
    if args.dry_run:
        print("DRY RUN: Skipped YouTube upload")
    if args.cleanup:
        print("Cleanup: generated media removed (see logs).")


if __name__ == "__main__":
    main()
