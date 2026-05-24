import argparse
import logging

from youtube_automation.config.loader import load_env, load_settings
from youtube_automation.utils.paths import ensure_workspace_dirs
from youtube_automation.pipeline import commentary_enabled, run_pipeline
from youtube_automation.media.thumbnail import source_thumbnail
from youtube_automation.sourcing import (
    instagram_sourcing_enabled,
    source_all_videos,
    try_prepare_instagram_session,
)
from youtube_automation.storage.sessions import save_session, new_session


def setup_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(message)s",
    )

    for noisy in ("urllib3", "praw", "prawcore", "requests", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["videos", "thumbnail", "pipeline", "shorts", "ai-preview"],
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
    parser.add_argument(
        "--thumbnail-shorts-orientation",
        action="store_true",
        help=(
            "With --mode thumbnail, load shorts config and source a portrait (9:16) thumbnail."
        ),
    )
    args = parser.parse_args()

    if args.thumbnail_shorts_orientation and args.mode != "thumbnail":
        parser.error(
            "--thumbnail-shorts-orientation is only allowed with --mode thumbnail"
        )
    load_env(args.channel)
    setup_logging(args.debug)

    logger = logging.getLogger(__name__)
    use_shorts_config = (
        args.mode == "shorts"
        or (args.mode == "thumbnail" and args.thumbnail_shorts_orientation)
    )
    settings = load_settings(args.channel, shorts=use_shorts_config)
    ensure_workspace_dirs()

    if args.no_commentary or args.core_only:
        settings.setdefault("commentary", {})["enabled"] = False

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

    target_dur = settings.get("final_target_duration")
    every_n = settings.get("commentary", {}).get("every_nth", 3)
    commentary_on = commentary_enabled(settings)
    music_on = settings.get("music", {}).get("enabled", True)
    ai_meta_on = settings.get("publishing", {}).get("ai_metadata", {}).get("enabled", False)
    commentary_status = (
        f"every {every_n}" if commentary_on and every_n > 0 else "off"
    )

    if args.mode == "ai-preview":
        from youtube_automation.ai.preview import run_ai_preview

        run_ai_preview(settings)
        return

    if args.mode == "shorts":
        sc = settings.get("shorts") or {}
        clip_mn = sc.get("clip_count_min")
        clip_mx = sc.get("clip_count_max")
        seg_cap = sc.get("max_segment_duration_sec")
        comp_gate = sc.get("target_compilation_duration_sec")
        extras = []
        if comp_gate is not None:
            extras.append(f"compilation gate ≥{comp_gate}s")
        extra_txt = f" | {'; '.join(extras)}" if extras else ""
        logger.info(
            "Channel: %s | Mode: shorts | Shorts clips (YAML): %s-%s | Segment cap: %ss%s "
            "| Commentary: %s | Music: %s | AI metadata: %s",
            args.channel,
            clip_mn,
            clip_mx,
            seg_cap,
            extra_txt,
            commentary_status,
            "on" if music_on else "off",
            "on" if ai_meta_on else "off",
        )
    else:
        logger.info(
            "Channel: %s | Mode: %s | Target: %s min | Commentary: %s | Music: %s | AI metadata: %s",
            args.channel,
            args.mode,
            target_dur,
            commentary_status,
            "on" if music_on else "off",
            "on" if ai_meta_on else "off",
        )

    if args.mode == "thumbnail":
        logger.info(
            "Thumbnail canvas: %s (content_type=%s)",
            (
                "portrait 1080×1920"
                if settings.get("content_type") == "shorts"
                else "landscape 1920×1080"
            ),
            settings.get("content_type", "long_form"),
        )
        thumb = source_thumbnail(settings)
        session = new_session({"thumbnail": thumb or {}, "clips": [], "num_clips": 0})
        save_session(session, settings)
        print(thumb)
        return

    if args.mode == "videos":
        try_prepare_instagram_session(settings)
        clips = source_all_videos(settings)
        session = new_session({"clips": clips, "num_clips": len(clips)})
        save_session(session, settings)
        ig_n = sum(1 for c in clips if c.get("source") == "instagram")
        print(f"Sourced {len(clips)} clips ({ig_n} Instagram, {len(clips) - ig_n} Reddit).")
        return

    if args.mode == "shorts":
        from youtube_automation.shorts_pipeline import run_shorts_pipeline

        session = run_shorts_pipeline(
            settings, dry_run=args.dry_run, cleanup=args.cleanup
        )
    else:
        session = run_pipeline(settings, dry_run=args.dry_run, cleanup=args.cleanup)
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
