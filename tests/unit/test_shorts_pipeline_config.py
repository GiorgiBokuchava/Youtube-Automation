import pytest

from youtube_automation.shorts_pipeline import run_shorts_pipeline


def test_shorts_pipeline_raises_when_disabled():
    settings = {
        "channel": {"name": "animals"},
        "shorts": {"enabled": False},
    }

    with pytest.raises(RuntimeError, match="disabled by config"):
        run_shorts_pipeline(settings, dry_run=True, cleanup=False)
