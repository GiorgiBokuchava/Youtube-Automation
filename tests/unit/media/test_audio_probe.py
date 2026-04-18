from pathlib import Path
from youtube_automation.media.audio.probe import analyze_clip_audio


def test_analyze_clip_audio_music_likely(mocker, tmp_path):
    fake_video = tmp_path / "clip.mp4"
    fake_video.write_bytes(b"fake")

    mocker.patch(
        "youtube_automation.media.audio.probe._detect_volume",
        return_value=(-22.0, -1.0),
    )

    mocker.patch(
        "youtube_automation.media.audio.probe._detect_silence_ratio",
        return_value=0.05,
    )

    analysis = analyze_clip_audio(fake_video)

    assert analysis.has_audio is True
    assert analysis.has_sustained_audio is True
    assert analysis.music_likely is True
