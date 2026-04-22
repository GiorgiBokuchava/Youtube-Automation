#!/usr/bin/env python3
"""
Test script to demonstrate fallback commentary functionality.

This script simulates a pipeline failure and tests the fallback commentary
mechanism that uses OpenRouter when video-capable models fail.
"""

import sys
import logging
import json
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from youtube_automation.ai.text.commentary import generate_commentary_video_first
from youtube_automation.ai.text.service import text_service
from youtube_automation.ai.text.types import TextRequest
from youtube_automation.ai.errors import QuotaExhaustedError
from youtube_automation.ai.text import registry as text_registry
from youtube_automation.ai.text.providers.openrouter import (
    fetch_free_openrouter_models,
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def mock_quota_exhausted_generate(*args, **kwargs):
    """Mock function that simulates quota exhaustion for video models."""
    raise QuotaExhaustedError("Video model quota exhausted")


def test_fallback_commentary():
    """Test the fallback commentary mechanism with real data from used_animals.json."""

    # Sample data from the JSON file
    sample_clip = {
        "id": "1qfkyhy",
        "title": "My cat makes this sound when he's about to attack someone",
        "selftext": "",
        "top_comments": [
            "At least he gives warning ⚠️",
            "War Cry! Prepare for the Claw!",
            "Battle cry!!!",
            "That's a fair warning tbf",
        ],
        "local_path": "out\\animals\\normalized_videos\\normalized_1qfkyhy.mp4",
    }

    print("=== Testing Fallback Commentary ===\n")

    # Test 1: Normal video-first generation (should work with real video)
    print("1. Testing normal video-first generation...")
    try:
        video_path = Path(sample_clip["local_path"])
        if video_path.exists():
            commentary, model_used, fallback_occurred = generate_commentary_video_first(
                video_path=video_path,
                title=sample_clip["title"],
                selftext=sample_clip["selftext"],
                top_comments=sample_clip["top_comments"],
                preferred_video_model="openrouter",  # Force OpenRouter
            )

            print(f"   ✅ Success!")
            print(f"   Commentary: '{commentary}'")
            print(f"   Model used: {model_used}")
            print(f"   Fallback occurred: {fallback_occurred}")
        else:
            print(f"   ⚠️  Video file not found: {video_path}")
            print("   Skipping video-first test...")
    except Exception as e:
        print(f"   ❌ Failed: {e}")

    print("\n" + "=" * 50 + "\n")

    # Test 2: Simulated quota exhaustion fallback
    print("2. Testing fallback commentary (simulated quota exhaustion)...")

    # Temporarily patch the text service to simulate quota exhaustion
    original_generate = text_service.generate

    def mock_generate_with_quota_exhaustion(request, preferred_model=None):
        # If the request requires video capabilities, simulate quota exhaustion
        if (
            request.get_required_capabilities()
            and "video" in request.get_required_capabilities()
        ):
            raise QuotaExhaustedError(
                "Video model quota exhausted - simulating failure"
            )
        # For text-only fallback, force OpenRouter by ignoring preferred_model and using openrouter
        return original_generate(request, preferred_model="openrouter")

    # Apply the mock
    text_service.generate = mock_generate_with_quota_exhaustion

    try:
        video_path = Path(sample_clip["local_path"])
        commentary, model_used, fallback_occurred = generate_commentary_video_first(
            video_path=video_path,  # This will trigger the fallback
            title=sample_clip["title"],
            selftext=sample_clip["selftext"],
            top_comments=sample_clip["top_comments"],
            preferred_video_model="openrouter",
        )

        print(f"   ✅ Fallback successful!")
        print(f"   Commentary: '{commentary}'")
        print(f"   Model used: {model_used}")
        print(f"   Fallback occurred: {fallback_occurred}")

    except Exception as e:
        print(f"   ❌ Fallback failed: {e}")
    finally:
        # Restore original generate method
        text_service.generate = original_generate

    print("\n" + "=" * 50 + "\n")

    # Test 3: Direct text-only fallback (no video file)
    print("3. Testing direct text-only fallback (no video)...")

    try:
        # Use a non-existent video path to force fallback
        fake_video_path = Path("non_existent_video.mp4")
        commentary, model_used, fallback_occurred = generate_commentary_video_first(
            video_path=fake_video_path,
            title=sample_clip["title"],
            selftext=sample_clip["selftext"],
            top_comments=sample_clip["top_comments"],
            preferred_video_model="openrouter",
        )

        print(f"   ✅ Text-only fallback successful!")
        print(f"   Commentary: '{commentary}'")
        print(f"   Model used: {model_used}")
        print(f"   Fallback occurred: {fallback_occurred}")

    except Exception as e:
        print(f"   ❌ Text-only fallback failed: {e}")

    print("\n" + "=" * 50 + "\n")

    # Test 4: Test the fallback prompt directly
    print("4. Testing fallback prompt generation...")

    try:
        from youtube_automation.ai.text.commentary import _post_fallback_prompt

        fallback_prompt = _post_fallback_prompt(
            title=sample_clip["title"],
            selftext=sample_clip["selftext"],
            comments=sample_clip["top_comments"],
        )

        print("   ✅ Fallback prompt generated:")
        print("   " + "=" * 40)
        print(f"   {fallback_prompt}")
        print("   " + "=" * 40)

        # Test the prompt with OpenRouter directly
        req = TextRequest(text=fallback_prompt)
        result = text_service.generate(req, preferred_model="openrouter")

        print(f"\n   ✅ OpenRouter response: '{result}'")

    except Exception as e:
        print(f"   ❌ Fallback prompt test failed: {e}")


def test_multiple_clips():
    """Test fallback commentary on multiple clips from the JSON data."""

    print("\n" + "=" * 60)
    print("Testing Multiple Clips with Fallback")
    print("=" * 60)

    # Load real data from the JSON file
    try:
        import json

        with open("config/used_animals.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        # Test first 3 clips
        clips = data[0]["clips"][:3]

        for i, clip in enumerate(clips, 1):
            print(f"\n{i}. Testing clip: {clip['title'][:50]}...")

            try:
                # Force text-only fallback by using non-existent video
                fake_video_path = Path(f"fake_{clip['id']}.mp4")

                commentary, model_used, fallback_occurred = (
                    generate_commentary_video_first(
                        video_path=fake_video_path,
                        title=clip["title"],
                        selftext=clip.get("selftext", ""),
                        top_comments=clip.get("top_comments", [])[
                            :3
                        ],  # Use first 3 comments
                        preferred_video_model="openrouter",
                    )
                )

                print(f"   ✅ Commentary: '{commentary}'")
                print(f"   Model: {model_used}, Fallback: {fallback_occurred}")

            except Exception as e:
                print(f"   ❌ Failed: {e}")

    except Exception as e:
        print(f"Failed to load test data: {e}")


def run_openrouter_fallback_for_single_post() -> None:
    """Run a demo that exercises ONLY the OpenRouter text fallback.

    This:
    - Picks one clip from config/used_animals.json that has video + comments
    - Simulates video-model failure (so we go straight to post-context fallback)
    - Forces text_service to use OpenRouter only (no Gemini at all)
    - Prints the chosen post, the comments used for context, and the
      OpenRouter-generated fallback commentary.
    """

    print("\n" + "=" * 60)
    print("OpenRouter Fallback Demo (Single Post)")
    print("=" * 60)

    # 1) Pick a clip from used_animals.json
    clips_file = Path("config/used_animals.json")
    try:
        data = json.loads(clips_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Failed to load {clips_file}: {e}")
        return

    chosen_clip = None
    # Iterate from the bottom up to find a fresh clip
    for batch in reversed(data):
        for clip in reversed(batch.get("clips", [])):
            has_video_meta = bool(clip.get("local_path") or clip.get("source_url"))
            has_comments = bool(clip.get("top_comments"))
            no_commentary = not clip.get("commentary_text")
            if has_video_meta and has_comments and no_commentary:
                chosen_clip = clip
                break
        if chosen_clip:
            break

    # Fallback: if all clips already have commentary_text, just take the first
    if not chosen_clip:
        first_batch = data[0] if data else {}
        clips = first_batch.get("clips", [])
        if not clips:
            print("No clips found in used_animals.json")
            return
        chosen_clip = clips[0]

    top_comments = (chosen_clip.get("top_comments") or [])[:5]

    print("\nChosen post for fallback:")
    print(f"  ID:         {chosen_clip.get('id')}")
    print(f"  Subreddit:  {chosen_clip.get('subreddit')}")
    print(f"  Title:      {chosen_clip.get('title')}")
    print(f"  Permalink:  {chosen_clip.get('permalink')}")
    print(f"  Local path: {chosen_clip.get('local_path')}")

    print("\nComments used for context (up to 5):")
    if not top_comments:
        print("  (no comments available)")
    else:
        for idx, c in enumerate(top_comments, start=1):
            print(f"  {idx}. {c}")

    # 2) Discover an OpenRouter text model to use
    try:
        free_models = fetch_free_openrouter_models()
    except Exception as e:
        print(f"\nFailed to fetch OpenRouter models: {e}")
        print("Ensure OPENROUTER_API_KEYS is set correctly.")
        return

    if not free_models:
        print("\nNo free OpenRouter models found.")
        return

    openrouter_model = free_models[0]
    print(f"\nUsing OpenRouter model: {openrouter_model}")

    # 3) Patch text_service so:
    #    - Any *video* request raises QuotaExhaustedError (simulating video failure)
    #    - Any *text-only* request is forced through OpenRouter with the model above
    if "openrouter" not in text_service._providers:
        print("OpenRouter provider is not available in text_service._providers")
        return

    original_providers = text_service._providers.copy()
    original_generate = text_service.generate

    # Restrict providers to OpenRouter only
    text_service._providers = {
        "openrouter": original_providers["openrouter"],
    }

    def generate_with_forced_openrouter(
        request: TextRequest, preferred_model: str | None = None
    ) -> str:
        caps = request.get_required_capabilities()
        if "video_in" in caps:
            # Simulate video-capable model failure (e.g., Gemini quota/rate limit)
            raise QuotaExhaustedError(
                "Simulated video quota exhaustion - forcing text-only OpenRouter fallback"
            )

        # For pure text requests, ignore preferred_model and always use our OpenRouter model
        return original_generate(request, preferred_model=openrouter_model)

    text_service.generate = generate_with_forced_openrouter

    # 4) Run the normal commentary pipeline function, which will:
    #    - Try video-aware commentary (we force it to fail)
    #    - Fall back to post-context commentary (which we force through OpenRouter)
    try:
        video_path = Path(chosen_clip.get("local_path") or "missing_video.mp4")
        commentary, model_used, fallback_occurred = generate_commentary_video_first(
            video_path=video_path,
            title=chosen_clip.get("title", ""),
            selftext=chosen_clip.get("selftext", ""),
            top_comments=top_comments,
            preferred_video_model=openrouter_model,
        )

        print("\nResulting fallback commentary:")
        print(f"  Text:   {commentary}")
        print(f"  Model:  {model_used}")
        print(f"  Fallback occurred: {fallback_occurred}")

    except Exception as e:
        print(f"\nOpenRouter fallback demo failed: {e}")

    finally:
        # Restore original text_service state
        text_service.generate = original_generate
        text_service._providers = original_providers


if __name__ == "__main__":
    print("🧪 Testing OpenRouter Fallback Commentary")
    print("=" * 60)

    # Run only the OpenRouter-only fallback demo to avoid any Gemini usage
    run_openrouter_fallback_for_single_post()

    print("\n🎉 OpenRouter fallback demo completed!")
