from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from youtube_automation.ai.text.commentary import generate_commentary_video_first
from youtube_automation.ai.tts.service import tts_service
from youtube_automation.ai.tts.types import TTSRequest
from youtube_automation.media.audio import analyze_clip_audio
from youtube_automation.media.composition import render_clip, stitch_clips
from youtube_automation.media.thumbnail import source_thumbnail
from youtube_automation.media.video import source_videos
from youtube_automation.media.video_processing import batch_normalize_videos
from youtube_automation.media.music import add_background_music
from youtube_automation.storage.sessions import new_session, save_session
from youtube_automation.youtube.auth import ensure_youtube_refresh_token
from youtube_automation.youtube.upload import upload_video
from youtube_automation.publishing.metadata import build_metadata
from youtube_automation.publishing.ai_metadata import generate_ai_metadata


def _clip_ref(clip: dict) -> str:
    return str(clip.get("id", "unknown"))


def _record_error(
    errors: list[dict],
    *,
    step: str,
    exc: BaseException,
    clip: dict | None = None,
) -> None:
    entry = {
        "step": step,
        "error": f"{type(exc).__name__}: {exc}",
        "clip_id": _clip_ref(clip) if clip else None,
    }
    errors.append(entry)
    cid = entry["clip_id"]
    if cid:
        logger.warning("%s failed for clip %s: %s", step, cid, exc)
    else:
        logger.warning("%s failed: %s", step, exc)


def run_pipeline(settings: dict, dry_run: bool = False, cleanup: bool = False) -> dict:
    channel = settings.get("channel", {}).get("name", "default")
    base_out = Path("out") / channel

    pipeline_errors: list[dict] = []
    run_succeeded = False

    try:
        VOICEOVERS_DIR = base_out / "voiceovers"
        RENDERED_DIR = base_out / "rendered_clips"
        OUTPUT_DIR = base_out / "outputs"

        VOICEOVERS_DIR.mkdir(parents=True, exist_ok=True)
        RENDERED_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        if not dry_run:
            ensure_youtube_refresh_token()

        clips = source_videos(settings)
        thumb = source_thumbnail(settings)

        if not clips:
            raise ValueError("No clips sourced, aborting pipeline")

        if not thumb:
            raise ValueError("No thumbnail sourced, aborting pipeline")

        # Normalize video aspect ratios
        video_norm_cfg = settings.get("video_normalization", {})
        target_width = int(video_norm_cfg.get("target_width", 1920))
        target_height = int(video_norm_cfg.get("target_height", 1080))
        padding_method = video_norm_cfg.get("padding_method", "black")

        if video_norm_cfg:
            normalized_dir = base_out / "normalized_videos"
            video_paths = [Path(clip["local_path"]) for clip in clips]
            # Create mapping of video paths to authors
            authors = {
                Path(clip["local_path"]): clip.get("author", "unknown")
                for clip in clips
            }
            normalized_paths = batch_normalize_videos(
                video_paths,
                normalized_dir,
                target_width,
                target_height,
                padding_method,
                authors,
            )
            for clip in clips:
                original_path = Path(clip["local_path"])
                if original_path in normalized_paths:
                    clip["original_local_path"] = clip["local_path"]
                    clip["local_path"] = str(normalized_paths[original_path])

        commentary_cfg = settings.get("commentary", {})
        every_n = int(commentary_cfg.get("every_nth", 3))
        tts_voices = commentary_cfg.get("tts_voices", {})
        preferred_video_model = commentary_cfg.get("preferred_video_model", None)
        preferred_tts_model = commentary_cfg.get("preferred_tts_model", None)
        theme = commentary_cfg.get("theme", "funny")

        for i, clip in enumerate(clips):
            if every_n <= 0 or (i % every_n) != 0:
                continue

            try:
                video_path = Path(clip["local_path"])
                title = clip.get("title", "")
                selftext = clip.get("selftext", "")
                top_comments = clip.get("top_comments", []) or []

                try:
                    commentary, model_used, fallback_occurred = (
                        generate_commentary_video_first(
                            video_path=video_path,
                            title=title,
                            selftext=selftext,
                            top_comments=top_comments,
                            preferred_video_model=preferred_video_model,
                            theme=theme,
                        )
                    )

                    clip["commentary_text"] = commentary
                    clip["commentary_model"] = model_used
                    clip["commentary_fallback"] = fallback_occurred

                except Exception as e:
                    _record_error(pipeline_errors, step="commentary", exc=e, clip=clip)
                    continue

                audio = tts_service.synthesize(
                    TTSRequest(text=commentary, voice=None),
                    preferred_model=preferred_tts_model,
                    tts_voices=tts_voices,
                )

                out_path = VOICEOVERS_DIR / f"{clip['id']}_vo{audio.ext}"
                out_path.write_bytes(audio.data)

                clip["voiceover_path"] = str(out_path)
                clip["voiceover_provider"] = audio.provider
                clip["voiceover_model"] = audio.model
            except Exception as e:
                _record_error(pipeline_errors, step="commentary_tts", exc=e, clip=clip)
                continue

        for clip in clips:
            try:
                analysis = analyze_clip_audio(Path(clip["local_path"]))
                clip["audio_analysis"] = {
                    "has_audio": analysis.has_audio,
                    "mean_volume_db": analysis.mean_volume_db,
                    "max_volume_db": analysis.max_volume_db,
                    "silence_ratio": analysis.silence_ratio,
                    "has_sustained_audio": analysis.has_sustained_audio,
                    "music_likely": analysis.music_likely,
                }
            except Exception as e:
                _record_error(pipeline_errors, step="audio_analysis", exc=e, clip=clip)
                clip["audio_analysis"] = {
                    "has_audio": False,
                    "mean_volume_db": None,
                    "max_volume_db": None,
                    "silence_ratio": None,
                    "has_sustained_audio": False,
                    "music_likely": False,
                }

        rendered_paths: list[Path] = []
        for clip in clips:
            try:
                in_path = Path(clip["local_path"])
                out_path = RENDERED_DIR / f"{clip['id']}_rendered.mp4"

                voiceover = clip.get("voiceover_path")
                voiceover_path = Path(voiceover) if voiceover else None

                orig_vol = settings.get("audio", {}).get("original_clip_volume_db", 0.0)

                rendered = render_clip(
                    input_video=in_path,
                    output_video=out_path,
                    commentary_audio=voiceover_path,
                    commentary_offset_sec=0.45,
                    original_volume_db=orig_vol,
                    commentary_gain=settings.get("commentary", {}).get(
                        "commentary_gain", 1.0
                    ),
                )

                clip["rendered_path"] = str(rendered)
                rendered_paths.append(rendered)
            except Exception as e:
                _record_error(pipeline_errors, step="render_clip", exc=e, clip=clip)
                continue

        if not rendered_paths:
            raise ValueError("No successfully rendered clips available for stitching")

        stitched = stitch_clips(
            clip_paths=rendered_paths,
            output_path=OUTPUT_DIR / "final_raw.mp4",
        )

        final_with_music = add_background_music(
            video_path=stitched,
            output_path=OUTPUT_DIR / "final.mp4",
            settings=settings,
        )

        meta = build_metadata(settings, clips)

        ai_cfg = settings.get("publishing", {}).get("ai_metadata", {})
        if ai_cfg.get("enabled", False):
            try:
                ai_meta = generate_ai_metadata(settings=settings, clips=clips)

                if ai_meta.get("title"):
                    meta["title"] = ai_meta["title"]

                if ai_meta.get("description"):
                    meta["description"] = ai_meta["description"]

                if ai_meta.get("hashtags"):
                    meta["tags"] = ai_meta["hashtags"]

            except Exception as e:
                _record_error(pipeline_errors, step="ai_metadata", exc=e)

        url = None
        if not dry_run:
            url = upload_video(
                video_path=Path(final_with_music),
                title=meta["title"],
                description=meta["description"],
                tags=meta["tags"],
                category_id=meta["category_id"],
                privacy_status=meta["privacy_status"],
                thumbnail_path=Path(thumb["path"]) if thumb else None,
            )

        session = new_session(
            {
                "clips": clips,
                "num_clips": len(clips),
                "thumbnail": thumb or {},
                "output_path": str(final_with_music),
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
                _cleanup_generated_files(base_out)
            except Exception as e:
                logger.warning(
                    "Failed to clean up generated files under %s: %s", base_out, e
                )


def _cleanup_generated_files(base_out: Path) -> None:
    """Clean up generated media files while preserving session history."""
    logger = logging.getLogger(__name__)
    logger.info("Cleaning up generated files...")

    # Directories to clean
    cleanup_dirs = [
        base_out / "voiceovers",
        base_out / "rendered_clips",
        base_out / "normalized_videos",
        base_out / "outputs",
        Path("thumbnails"),
    ]

    # Also clean downloads directory
    from youtube_automation.utils.paths import DOWNLOADS

    cleanup_dirs.append(DOWNLOADS)

    cleaned_count = 0

    # Clean directories (files only; keep directory structure)
    for dir_path in cleanup_dirs:
        if dir_path.exists():
            for file_path in dir_path.iterdir():
                if file_path.is_file():
                    try:
                        file_path.unlink()
                        cleaned_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to delete {file_path}: {e}")

    logger.info("Cleaned up %s generated files", cleaned_count)
