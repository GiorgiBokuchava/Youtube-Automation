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
from youtube_automation.storage.sessions import new_session, save_session


VOICEOVERS_DIR = Path("voiceovers")
VOICEOVERS_DIR.mkdir(exist_ok=True)

RENDERED_DIR = Path("rendered_clips")
RENDERED_DIR.mkdir(exist_ok=True)

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


def run_pipeline(settings: dict) -> dict:
    clips = source_videos(settings)
    thumb = source_thumbnail(settings)

    # Normalize video aspect ratios
    video_norm_cfg = settings.get("video_normalization", {})
    target_width = int(video_norm_cfg.get("target_width", 1920))
    target_height = int(video_norm_cfg.get("target_height", 1080))
    padding_method = video_norm_cfg.get("padding_method", "black")

    if video_norm_cfg:
        normalized_dir = Path("normalized_videos")
        video_paths = [Path(clip["local_path"]) for clip in clips]
        normalized_paths = batch_normalize_videos(
            video_paths,
            normalized_dir,
            target_width,
            target_height,
            padding_method,
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

    for i, clip in enumerate(clips):
        if every_n <= 0 or (i % every_n) != 0:
            continue

        video_path = Path(clip["local_path"])
        title = clip.get("title", "")
        selftext = clip.get("selftext", "")
        top_comments = clip.get("top_comments", []) or []

        commentary = generate_commentary_video_first(
            video_path=video_path,
            title=title,
            selftext=selftext,
            top_comments=top_comments,
            preferred_video_model=preferred_video_model,
        )

        clip["commentary_text"] = commentary

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

    for clip in clips:
        analysis = analyze_clip_audio(Path(clip["local_path"]))
        clip["audio_analysis"] = {
            "has_audio": analysis.has_audio,
            "mean_volume_db": analysis.mean_volume_db,
            "max_volume_db": analysis.max_volume_db,
            "silence_ratio": analysis.silence_ratio,
            "has_sustained_audio": analysis.has_sustained_audio,
            "music_likely": analysis.music_likely,
        }

    rendered_paths: list[Path] = []
    for clip in clips:
        in_path = Path(clip["local_path"])
        out_path = RENDERED_DIR / f"{clip['id']}_rendered.mp4"

        voiceover = clip.get("voiceover_path")
        voiceover_path = Path(voiceover) if voiceover else None

        rendered = render_clip(
            input_video=in_path,
            output_video=out_path,
            commentary_audio=voiceover_path,
            commentary_offset_sec=0.45,
            ducking_db=-12.0,
        )

        clip["rendered_path"] = str(rendered)
        rendered_paths.append(rendered)

    final_path = OUTPUT_DIR / "final.mp4"
    stitched = stitch_clips(clip_paths=rendered_paths, output_path=final_path)

    session = new_session(
        {
            "clips": clips,
            "num_clips": len(clips),
            "thumbnail": thumb or {},
            "output_path": str(stitched),
        }
    )

    save_session(session, settings)
    return session
