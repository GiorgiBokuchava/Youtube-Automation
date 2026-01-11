from dotenv import load_dotenv
import time

from youtube_automation.ai.text.service import ai_service
from youtube_automation.ai.text.types import AIRequest
from youtube_automation.ai.text.registry import get_models_by_provider

load_dotenv()

PROMPT = (
    "Write ONE funny YouTube Shorts caption (max 12 words). "
    "Exactly ONE punchy verb. "
    "No emojis. No questions. Just plain text. "
    "Scene: an excited dog zooming around a kitchen. "
    "Return ONLY the caption text."
)

print("=" * 100)
print("AI FULL SWEEP — ALL NON-GEMINI MODELS")
print("=" * 100)

providers = ["openrouter"]

for provider in providers:
    models = get_models_by_provider(provider)

    print(f"\n{'-' * 80}")
    print(f"PROVIDER: {provider} ({len(models)} models)")
    print(f"{'-' * 80}")

    for spec in models:
        model = spec["model"]

        print(f"\n▶ MODEL: {model}")
        start = time.time()

        try:
            result = ai_service.generate(
                request=AIRequest(text=PROMPT),
                preferred_model=model,
            )

            elapsed = time.time() - start

            if result:
                print(f"  ✅ SUCCESS ({elapsed:.2f}s)")
                print(f"     → {result}")
            else:
                print(f"  ⚠️  EMPTY RESULT ({elapsed:.2f}s)")

        except Exception as exc:
            elapsed = time.time() - start
            print(f"  ❌ ERROR ({elapsed:.2f}s)")
            print(f"     {type(exc).__name__}: {exc}")

print("\n" + "=" * 100)
print("ALL NON-GEMINI TEST COMPLETE")
print("=" * 100)
