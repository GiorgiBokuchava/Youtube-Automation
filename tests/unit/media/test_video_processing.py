from youtube_automation.media.video_processing import normalize_video_aspect_ratio


def test_normalize_returns_original_on_failure(tmp_path):
    fake = tmp_path / "bad.mp4"
    fake.write_bytes(b"x")

    out = normalize_video_aspect_ratio(
        fake,
        tmp_path / "out.mp4",
        1920,
        1080,
    )

    assert out == fake
