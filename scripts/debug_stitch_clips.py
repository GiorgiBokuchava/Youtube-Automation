from pathlib import Path
from youtube_automation.media.composition import stitch_clips

CLIPS = [
    Path("rendered_clips/1pxg8lt_rendered.mp4"),
    Path("rendered_clips/1q0jn2r_rendered.mp4"),
    Path("rendered_clips/1q2vmkd_rendered.mp4"),
]

OUT = Path("debug_outputs/stitched.mp4")
OUT.parent.mkdir(exist_ok=True)

print("Stitching clips...")
stitch_clips(clip_paths=CLIPS, output_path=OUT)

print("Saved:", OUT)
