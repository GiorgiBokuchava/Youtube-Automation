import os
import sys
from pathlib import Path
from shutil import which
from typing import Optional


def ensure_ffmpeg() -> Optional[str]:
    ffdir = os.getenv("FFMPEG_DIR")
    if ffdir:
        ffmpeg = Path(ffdir, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        ffprobe = Path(ffdir, "ffprobe.exe" if os.name == "nt" else "ffprobe")
        if ffmpeg.exists() and ffprobe.exists():
            return ffdir

    if which("ffmpeg") and which("ffprobe"):
        return None

    print("[fatal] ffmpeg/ffprobe not found", file=sys.stderr)
    sys.exit(1)


def ffmpeg_bin() -> str:
    ffmpeg_dir = ensure_ffmpeg()
    return "ffmpeg" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffmpeg")


def ffprobe_bin() -> str:
    ffmpeg_dir = ensure_ffmpeg()
    return "ffprobe" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffprobe")
