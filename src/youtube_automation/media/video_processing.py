from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from .ffmpeg import ensure_ffmpeg


def _find_font_path() -> Optional[str]:
    system = platform.system()
    if system == "Windows":
        candidates = [
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/segoeui.ttf"),
        ]
    elif system == "Darwin":
        candidates = [
            Path("/System/Library/Fonts/Helvetica.ttc"),
            Path("/Library/Fonts/Arial.ttf"),
        ]
    else:
        candidates = [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
            Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
            Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
        ]

    for p in candidates:
        if p.exists():
            return str(p)
    return None


def _build_author_filter(author: str | None, target_height: int) -> str:
    """Return a drawtext filter fragment, or empty string."""
    if not author:
        return ""
    font_path = _find_font_path()
    if not font_path:
        logger.warning("No suitable font found; skipping author watermark")
        return ""
    font_size = max(16, int(target_height * 0.025))
    escaped_author = author.replace("'", "\\'").replace(":", "\\:")
    # Convert backslashes first, THEN escape colons for FFmpeg filter syntax.
    # Wrong order would turn the escape `\:` back into `/:` via the backslash replacement.
    escaped_font = font_path.replace("\\", "/").replace(":", "\\:")
    return (
        f"drawtext=text='{escaped_author}':fontcolor=white@0.8"
        f":fontsize={font_size}:x=10:y=h-th-10"
        f":fontfile='{escaped_font}'"
    )


def _probe_dimensions(
    input_path: Path, ffprobe: str
) -> tuple[int, int] | None:
    cmd = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0", str(input_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        out = result.stdout.strip()
        if "x" not in out:
            return None
        w, h = map(int, out.split("x"))
        return w, h
    except (ValueError, AttributeError):
        return None


def normalize_video_aspect_ratio(
    input_path: Path,
    output_path: Path,
    target_width: int,
    target_height: int,
    padding_method: str = "blur",
    author: str = None,
) -> Path:
    """Normalize video to target aspect ratio.

    padding_method:
        "blur"  – frosted-glass background (blurred + darkened copy of the
                  source) with the sharp original centred on top.
        "black" – plain black bars on the shorter axis.
    """
    tw, th = target_width, target_height
    target_ratio = tw / th

    ffmpeg_dir = ensure_ffmpeg()
    ffprobe = "ffprobe" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffprobe")

    dims = _probe_dimensions(input_path, ffprobe)
    if dims is None:
        return input_path

    src_w, src_h = dims
    current_ratio = src_w / src_h

    if src_w == tw and src_h == th:
        # Already the exact target resolution — just copy, no re-encode needed.
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, output_path)
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = "ffmpeg" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffmpeg")
    author_filt = _build_author_filter(author, th)

    if padding_method == "blur":
        cmd = _blur_cmd(ffmpeg, input_path, output_path, tw, th, author_filt)
    else:
        cmd = _pad_cmd(ffmpeg, input_path, output_path, tw, th, author_filt)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Skip the FFmpeg version header lines; show the actual error lines.
        error_lines = [
            ln for ln in result.stderr.splitlines()
            if any(kw in ln.lower() for kw in ("error", "invalid", "fail", "no option"))
        ]
        summary = "; ".join(error_lines[-3:]) if error_lines else result.stderr[-300:]
        logger.warning(
            "Normalization failed for %s (exit %d): %s",
            input_path.name, result.returncode, summary,
        )
        return input_path

    return output_path


def _blur_cmd(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    tw: int,
    th: int,
    author_filt: str,
) -> list[str]:
    """Build ffmpeg command for the frosted-glass blur background."""
    # Background: cover frame, blur. Foreground: fit inside tw×th without stretching
    # (scale=W:H without force_original_aspect_ratio distorts non-exact matches).
    bg = (
        f"scale={tw}:{th}:force_original_aspect_ratio=increase,"
        f"crop={tw}:{th},"
        f"boxblur=20:5,"
        f"eq=brightness=-0.08"
    )
    fg = f"scale={tw}:{th}:force_original_aspect_ratio=decrease"
    overlay = "overlay=(W-w)/2:(H-h)/2"

    fc = f"[0:v]{bg}[bg];[0:v]{fg}[fg];[bg][fg]{overlay}"
    if author_filt:
        fc += f",{author_filt}"
    fc += "[out]"

    return [
        ffmpeg, "-i", str(input_path),
        "-filter_complex", fc,
        "-map", "[out]", "-map", "0:a?",
        "-c:a", "copy", "-y", str(output_path),
    ]


def _pad_cmd(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    tw: int,
    th: int,
    author_filt: str,
) -> list[str]:
    """Build ffmpeg command for plain black-bar padding (letterbox / pillarbox)."""
    parts = [
        f"scale={tw}:{th}:force_original_aspect_ratio=decrease",
        f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=black",
    ]
    if author_filt:
        parts.append(author_filt)

    return [
        ffmpeg, "-i", str(input_path),
        "-vf", ",".join(parts),
        "-c:a", "copy", "-y", str(output_path),
    ]


def batch_normalize_videos(
    video_paths: list[Path],
    output_dir: Path,
    target_width: int,
    target_height: int,
    padding_method: str = "blur",
    authors: dict[Path, str] = None,
) -> dict[Path, Path]:
    """Normalize multiple videos to target aspect ratio."""
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_paths = {}
    authors = authors or {}

    for video_path in video_paths:
        output_path = output_dir / f"normalized_{video_path.name}"
        author = authors.get(video_path)
        try:
            normalized = normalize_video_aspect_ratio(
                video_path,
                output_path,
                target_width,
                target_height,
                padding_method,
                author,
            )
            normalized_paths[video_path] = normalized
        except Exception as e:
            logger.warning("Normalization failed for %s, using original: %s", video_path.name, e)
            normalized_paths[video_path] = video_path

    return normalized_paths
