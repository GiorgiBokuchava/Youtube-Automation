from youtube_automation.config.loader import load_env

load_env("dashcam")
import os, json, requests

api_key = os.getenv("DASHCAM_OPENROUTER_API_KEYS", "").split(",")[0].strip()
resp = requests.get(
    "https://openrouter.ai/api/v1/models",
    headers={"Authorization": f"Bearer {api_key}"},
    timeout=10,
)
data = resp.json()["data"]


def get_input_modalities(m):
    return m.get("architecture", {}).get("input_modalities") or []


free = [m for m in data if m["id"].endswith(":free")]
print(f"Total free models: {len(free)}")

# Unique modalities across all free models
all_mods = set()
for m in free:
    all_mods.update(get_input_modalities(m))
print(f"Unique input modalities across free models: {sorted(all_mods)}")
print()

video_free = [m for m in free if "video" in get_input_modalities(m)]
image_free = [m for m in free if "image" in get_input_modalities(m)]
text_only_free = [m for m in free if get_input_modalities(m) == ["text"]]

print(f"Free models with video input: {len(video_free)}")
for m in video_free:
    print(f"  {m['id']:60s}  {get_input_modalities(m)}")
print()
print(f"Free models with image input: {len(image_free)}")
for m in image_free:
    print(f"  {m['id']:60s}  {get_input_modalities(m)}")
print()
print(f"Free models with text-only input: {len(text_only_free)}")

# Also check ALL models (not just free) for video
all_video = [m for m in data if "video" in get_input_modalities(m)]
print()
print(f"ALL models with video input (paid + free): {len(all_video)}")
for m in all_video:
    print(
        f"  {m['id']:60s}  free={m['id'].endswith(':free')}  {get_input_modalities(m)}"
    )
