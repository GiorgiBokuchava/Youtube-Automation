from youtube_automation.media.video import _get_reddit_source_config


def test_reddit_sourcing_falls_back_to_post_config():
    settings = {
        "post": {
            "min_duration": 1,
            "max_duration": 10,
            "min_score": 350,
            "min_ratio": 0.8,
        }
    }

    cfg = _get_reddit_source_config(settings)

    assert cfg["min_duration"] == 1
    assert cfg["max_duration"] == 10
    assert cfg["min_score"] == 350
    assert cfg["min_ratio"] == 0.8
    assert cfg["over_source_pct"] == 0


def test_reddit_sourcing_overrides_post_when_present():
    settings = {
        "post": {
            "min_duration": 1,
            "max_duration": 10,
            "min_score": 350,
            "min_ratio": 0.8,
        },
        "sourcing": {
            "reddit": {
                "min_duration": 2,
                "min_score": 500,
                "min_ratio": 0.9,
            }
        },
    }

    cfg = _get_reddit_source_config(settings)

    assert cfg["min_duration"] == 2
    assert cfg["max_duration"] == 10
    assert cfg["min_score"] == 500
    assert cfg["min_ratio"] == 0.9
    assert cfg["over_source_pct"] == 0
