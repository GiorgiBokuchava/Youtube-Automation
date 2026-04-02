from youtube_automation.publishing.metadata import build_metadata


def test_build_metadata_privacy_from_env(monkeypatch):
    monkeypatch.setenv("YT_PRIVACY", "private")
    meta = build_metadata(
        {
            "youtube": {
                "title_template": "T",
                "description_template": "D {credits}",
                "tags": [],
                "privacy_status": "public",
            }
        },
        [],
    )
    assert meta["privacy_status"] == "private"

    monkeypatch.setenv("YT_PRIVACY", "  UNLISTED ")
    meta2 = build_metadata(
        {
            "youtube": {
                "title_template": "T",
                "description_template": "D {credits}",
                "tags": [],
                "privacy_status": "public",
            }
        },
        [],
    )
    assert meta2["privacy_status"] == "unlisted"


def test_build_metadata_ignores_invalid_env_privacy(monkeypatch):
    monkeypatch.setenv("YT_PRIVACY", "not-a-status")
    meta = build_metadata(
        {
            "youtube": {
                "title_template": "T",
                "description_template": "D {credits}",
                "tags": [],
                "privacy_status": "public",
            }
        },
        [],
    )
    assert meta["privacy_status"] == "public"
