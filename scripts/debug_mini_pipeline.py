from pathlib import Path
from youtube_automation.media.audio import analyze_clip_audio
from youtube_automation.media.composition import render_clip, stitch_clips

NORMALIZED = Path("normalized_videos")
VOICEOVERS = Path("voiceovers")

OUT_DIR = Path("debug_outputs")
OUT_DIR.mkdir(exist_ok=True)

rendered = []

for i, video in enumerate(sorted(NORMALIZED.glob("*.mp4"))[:5]):
    vo = None
    if i % 3 == 0:
        vid = video.stem.replace("normalized_", "")
        candidate = VOICEOVERS / f"{vid}_vo.mp3"
        if candidate.exists():
            vo = candidate

    analysis = analyze_clip_audio(video)
    print(video.name, "music_likely =", analysis.music_likely)

    out = OUT_DIR / f"{video.stem}_rendered.mp4"
    render_clip(
        input_video=video,
        output_video=out,
        commentary_audio=vo,
    )
    rendered.append(out)

final = OUT_DIR / "mini_final.mp4"
stitch_clips(rendered, final)

print("Final video:", final)
