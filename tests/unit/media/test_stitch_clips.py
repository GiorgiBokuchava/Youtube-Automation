from pathlib import Path
from youtube_automation.media.composition.timeline import stitch_clips


def test_stitch_clips_writes_concat_file(mocker, tmp_path):
    clips = [
        tmp_path / "a.mp4",
        tmp_path / "b.mp4",
    ]

    for c in clips:
        c.write_bytes(b"mp4")

    out = tmp_path / "final.mp4"

    mocker.patch(
        "youtube_automation.media.composition.timeline.subprocess.run",
        return_value=type("P", (), {"returncode": 0, "stderr": ""})(),
    )

    stitched = stitch_clips(clip_paths=clips, output_path=out)

    assert stitched == out

    concat_file = tmp_path / "final_concat.txt"
    text = concat_file.read_text()

    assert "file" in text
    assert "a.mp4" in text
    assert "b.mp4" in text
