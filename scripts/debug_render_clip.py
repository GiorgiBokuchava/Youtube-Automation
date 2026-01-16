from pathlib import Path
from youtube_automation.media.composition import render_clip

VIDEO = Path("normalized_videos/normalized_1pxg8lt.mp4")
VOICEOVER = Path("voiceovers/1pxg8lt_vo.mp3")
OUT = Path("debug_outputs/rendered_with_commentary.mp4")

OUT.parent.mkdir(exist_ok=True)

print("Rendering clip...")
render_clip(
    input_video=VIDEO,
    output_video=OUT,
    commentary_audio=VOICEOVER,
    commentary_offset_sec=0.45,
    ducking_db=-12.0,
)

print("Saved:", OUT)
