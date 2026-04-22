from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from .ffmpeg import ensure_ffmpeg


def normalize_video_aspect_ratio(
    input_path: Path,
    output_path: Path,
    target_width: int,
    target_height: int,
    padding_method: str = "black",
    author: str = None,
) -> Path:
    """
    Normalize video to target aspect ratio with side padding only.

    Args:
        input_path: Input video file path
        output_path: Output video file path
        target_width: Target width in pixels
        target_height: Target height in pixels
        padding_method: "black" or "blur"
        author: Author name to burn into bottom left corner

    Returns:
        Path to the normalized video file
    """
    target_ratio = target_width / target_height

    # Get video info using ffprobe
    ffmpeg_dir = ensure_ffmpeg()
    ffprobe = "ffprobe" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffprobe")

    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=s=x:p=0",
        str(input_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return input_path  # Return original if we can't get info

    try:
        out = result.stdout.strip()
        if "x" not in out:
            return input_path

        width, height = map(int, out.split("x"))
    except (ValueError, AttributeError):
        return input_path

    current_ratio = width / height

    # If already within tolerance, copy to normalized folder
    if abs(current_ratio - target_ratio) < 0.01:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, output_path)
        return output_path

    # Calculate padding for side-only mode
    if current_ratio < target_ratio:
        # Video is narrower than target - pad sides
        new_height = target_height
        new_width = int(new_height * current_ratio)
        pad_width = target_width - new_width
        pad_left = pad_width // 2
        pad_right = pad_width - pad_left
        pad_top = 0
        pad_bottom = 0
    else:
        # Video is wider than target - crop to fit height, then pad sides if needed
        new_height = target_height
        new_width = int(new_height * current_ratio)

        # If still wider than target after scaling, crop more
        if new_width > target_width:
            new_width = target_width
            pad_width = 0
        else:
            pad_width = target_width - new_width

        pad_left = pad_width // 2
        pad_right = pad_width - pad_left
        pad_top = 0
        pad_bottom = 0

    # Build ffmpeg command
    ffmpeg = "ffmpeg" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffmpeg")

    # Create filter chain
    filter_chain = [f"scale={new_width}:{new_height}"]

    if pad_width > 0:
        pad_color = "black" if padding_method == "black" else "0x00000000"
        filter_chain.append(
            f"pad={target_width}:{target_height}:{pad_left}:{pad_top}:color={pad_color}"
        )

    # Add author text overlay if provided
    if author:
        # Position text at bottom left with some padding
        # Font size scaled to video resolution (about 2% of height)
        font_size = max(16, int(target_height * 0.025))
        # Escape special characters in author name for ffmpeg
        escaped_author = author.replace("'", "\\'").replace(":", "\\:")
        text_filter = f"drawtext=text='{escaped_author}':fontcolor=white@0.8:fontsize={font_size}:x=10:y=h-th-10:fontfile=/Windows/Fonts/arial.ttf"
        filter_chain.append(text_filter)

    filter_string = ",".join(filter_chain)

    cmd = [
        ffmpeg,
        "-i",
        str(input_path),
        "-vf",
        filter_string,
        "-c:a",
        "copy",  # Copy audio stream unchanged
        "-y",  # Overwrite output file
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return input_path  # Return original on failure

    return output_path


def batch_normalize_videos(
    video_paths: list[Path],
    output_dir: Path,
    target_width: int,
    target_height: int,
    padding_method: str = "black",
    authors: dict[Path, str] = None,
) -> dict[Path, Path]:
    """
    Normalize multiple videos to target aspect ratio.

    Args:
        video_paths: List of input video paths
        output_dir: Directory for normalized videos
        target_width: Target width in pixels
        target_height: Target height in pixels
        padding_method: "black" or "blur"
        authors: Dict mapping video paths to author names

    Returns:
        Dict mapping original paths to normalized paths
    """
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
            # Keep original path as fallback
            normalized_paths[video_path] = video_path

    return normalized_paths
