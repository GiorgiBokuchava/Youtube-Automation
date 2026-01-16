from __future__ import annotations

import subprocess
from pathlib import Path


from youtube_automation.media.ffmpeg import ensure_ffmpeg


def _ffmpeg_bin() -> str:
    ffmpeg_dir = ensure_ffmpeg()
    return "ffmpeg" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffmpeg")


def stitch_clips(*, clip_paths: list[Path], output_path: Path) -> Path:
    if not clip_paths:
        raise ValueError("clip_paths is empty")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    list_file = output_path.parent / f"{output_path.stem}_concat.txt"
    lines = [f"file '{p.resolve().as_posix()}'" for p in clip_paths]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = [
        _ffmpeg_bin(),
        "-hide_banner",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ]

    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {p.stderr}")

    return output_path
