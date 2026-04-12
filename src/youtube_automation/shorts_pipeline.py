"""End-to-end Shorts generation (search-driven topics, 9:16, ranked overlays)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from youtube_automation.ai.text.shorts_topic import (
    generate_shorts_topic,
    random_clip_count_if_needed,
)
from youtube_automation.media.composition.shorts_render import render_shorts_segment
from youtube_automation.media.composition.timeline import stitch_clips
from youtube_automation.media.music import add_background_music
from youtube_automation.media.shorts_fit import fit_video_to_portrait_box
from youtube_automation.media.shorts_sourcing import source_shorts_clips
from youtube_automation.pipeline import _record_error
from youtube_automation.publishing.shorts_metadata import build_shorts_metadata
from youtube_automation.storage.sessions import new_session, save_session
from youtube_automation.youtube.auth import ensure_youtube_refresh_token
from youtube_automation.youtube.upload import upload_video

logger = logging.getLogger(__name__)


def run_shorts_pipeline(
    settings: dict, dry_run: bool = False, cleanup: bool = False
) -> dict:
    channel = settings.get("channel", {}).get("name", "default")
    base_out = Path("out") / channel / "shorts"

    pipeline_errors: list[dict[str, Any]] = []
    run_succeeded = False

    try:
        FIT_DIR = base_out / "fitted"
        SEG_DIR = base_out / "segments"
        OUTPUT_DIR = base_out / "outputs"

        for d in (FIT_DIR, SEG_DIR, OUTPUT_DIR):
            d.mkdir(parents=True, exist_ok=True)

        if not dry_run:
            ensure_youtube_refresh_token()

        topic_plan = random_clip_count_if_needed(generate_shorts_topic(settings), settings)
        clips, main_title = source_shorts_clips(settings, topic_plan)

        if not clips:
            raise ValueError("No Shorts clips sourced; aborting")

        sc = settings.get("shorts") or {}
        max_seg = float(sc.get("max_segment_duration_sec", 22))

        segment_paths: list[Path] = []
        n = len(clips)
        for idx, clip in enumerate(clips):
            rank = n - idx
            cid = clip["id"]
            in_path = Path(clip["local_path"])
            fit_path = FIT_DIR / f"{cid}_fit.mp4"
            try:
                fit_video_to_portrait_box(
                    in_path,
                    fit_path,
                    max_duration_sec=max_seg,
                )
            except Exception as e:
                _record_error(
                    pipeline_errors,
                    step="shorts_fit",
                    exc=e,
                    clip=clip,
                )
                continue

            seg_path = SEG_DIR / f"{cid}_seg.mp4"
            try:
                render_shorts_segment(
                    fit_path,
                    seg_path,
                    main_title=main_title,
                    rank=rank,
                    caption=clip.get("overlay_caption") or clip.get("title", ""),
                )
                segment_paths.append(seg_path)
            except Exception as e:
                _record_error(
                    pipeline_errors,
                    step="shorts_render",
                    exc=e,
                    clip=clip,
                )
                continue

        if not segment_paths:
            raise ValueError("No Shorts segments rendered successfully")

        stitched = stitch_clips(
            clip_paths=segment_paths,
            output_path=OUTPUT_DIR / "stitched_raw.mp4",
        )

        music_on = settings.get("music", {}).get("enabled", True)
        final_out = OUTPUT_DIR / "final.mp4"
        if music_on:
            mixed = add_background_music(
                video_path=stitched,
                output_path=final_out,
                settings=settings,
            )
            if mixed.resolve() != final_out.resolve():
                shutil.copy2(mixed, final_out)
            final_path = final_out
        else:
            shutil.copy2(stitched, final_out)
            final_path = final_out

        meta = build_shorts_metadata(settings, main_title, clips)

        ai_cfg = settings.get("publishing", {}).get("ai_metadata", {})
        if ai_cfg.get("enabled", False):
            try:
                from youtube_automation.publishing.ai_metadata import generate_ai_metadata

                ai_meta = generate_ai_metadata(settings=settings, clips=clips)
                if ai_meta.get("title"):
                    meta["title"] = ai_meta["title"]
                if ai_meta.get("description"):
                    meta["description"] = ai_meta["description"]
                if ai_meta.get("hashtags"):
                    meta["tags"] = ai_meta["hashtags"]
            except Exception as e:
                _record_error(pipeline_errors, step="shorts_ai_metadata", exc=e)

        url = None
        if not dry_run:
            url = upload_video(
                video_path=Path(final_path),
                title=meta["title"],
                description=meta["description"],
                tags=meta["tags"],
                category_id=meta["category_id"],
                privacy_status=meta["privacy_status"],
                thumbnail_path=None,
            )

        session = new_session(
            {
                "content_type": "shorts",
                "clips": clips,
                "num_clips": len(clips),
                "topic": {
                    "topic_title": topic_plan.topic_title,
                    "search_query": topic_plan.search_query,
                    "clip_count_requested": topic_plan.clip_count,
                },
                "main_title": main_title,
                "thumbnail": {},
                "output_path": str(final_path),
                "youtube_url": url,
                "pipeline_errors": pipeline_errors,
            }
        )

        save_session(session, settings)
        run_succeeded = True
        return session

    finally:
        if cleanup and run_succeeded:
            try:
                _cleanup_shorts_files(base_out)
            except Exception as e:
                logger.warning("Shorts cleanup failed under %s: %s", base_out, e)


def _cleanup_shorts_files(base_out: Path) -> None:
    logger.info("Cleaning up Shorts generated media under %s", base_out)
    from youtube_automation.utils.paths import DOWNLOADS

    for dir_path in (base_out / "fitted", base_out / "segments", base_out / "outputs"):
        if dir_path.exists():
            for file_path in dir_path.iterdir():
                if file_path.is_file():
                    try:
                        file_path.unlink()
                    except OSError:
                        pass
    if DOWNLOADS.exists():
        for file_path in DOWNLOADS.iterdir():
            if file_path.is_file():
                try:
                    file_path.unlink()
                except OSError:
                    pass
