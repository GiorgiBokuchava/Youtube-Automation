from pathlib import Path
from youtube_automation.media.audio import analyze_clip_audio

VIDEO = Path("normalized_videos/normalized_1q0jn2r.mp4")

analysis = analyze_clip_audio(VIDEO)

print("Audio analysis:")
print(f"  has_audio        = {analysis.has_audio}")
print(f"  mean_volume_db   = {analysis.mean_volume_db}")
print(f"  max_volume_db    = {analysis.max_volume_db}")
print(f"  silence_ratio    = {analysis.silence_ratio}")
print(f"  sustained_audio  = {analysis.has_sustained_audio}")
print(f"  music_likely     = {analysis.music_likely}")
