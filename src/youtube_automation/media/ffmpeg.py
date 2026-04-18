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
