from dotenv import load_dotenv
from openai import OpenAI
import os
import time

load_dotenv()

API_KEY = os.getenv("G4F_API_KEY")

client = OpenAI(
    base_url="https://g4f.dev/v1",
    api_key=API_KEY,
)

PROMPT = (
    "Write ONE funny YouTube Shorts caption (max 12 words).\n"
    "Rules:\n"
    "- Exactly ONE punchy verb\n"
    "- No emojis\n"
    "- No questions\n"
    "Scene: an excited dog zooming around a kitchen like it owns the place.\n"
    "Return ONLY the caption text."
)

MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "allam-2-7b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3-32b",
    "moonshotai/kimi-k2-instruct-0905",
    "moonshotai/kimi-k2-instruct",
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    # Known non-text / special-purpose models
    # "whisper-large-v3",
    # "whisper-large-v3-turbo",
    # "playai-tts",
    # "playai-tts-arabic",
]

print("=" * 80)
print("GPT4Free model sweep (text-only)")
print("=" * 80)

for model in MODELS:
    print(f"\n▶ Testing model: {model}")
    start = time.time()

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": PROMPT}],
            temperature=0.8,
            max_tokens=40,
        )

        elapsed = time.time() - start
        text = (resp.choices[0].message.content or "").strip()

        if not text:
            print(f"⚠️  EMPTY RESPONSE ({elapsed:.2f}s)")
        else:
            print(f"✅ SUCCESS ({elapsed:.2f}s)")
            print(f"   → {text}")

    except Exception as exc:
        elapsed = time.time() - start
        print(f"❌ ERROR ({elapsed:.2f}s)")
        print(f"   {type(exc).__name__}: {exc}")

print("\n" + "=" * 80)
print("Sweep complete.")
print("=" * 80)
