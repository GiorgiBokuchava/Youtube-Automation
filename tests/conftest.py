import pytest
from pathlib import Path


@pytest.fixture
def dummy_video(tmp_path):
    p = tmp_path / "video.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    return p


@pytest.fixture
def minimal_settings():
    return {
        "channel": {"name": "test"},
        "final_target_duration": 0,
        "used_horizon_days": 1,
        "subreddits": [],
        "commentary": {
            "every_nth": 1,
            "tts_voices": {},
            "preferred_video_model": None,
            "preferred_tts_model": None,
        },
        "video_normalization": {},
        "youtube": {
            "title_template": "Test title",
            "description_template": "Desc\n{credits}",
            "tags": ["test"],
            "category_id": "15",
            "privacy_status": "public",
        },
        "publishing": {"ai_metadata": {"enabled": False}},
    }
