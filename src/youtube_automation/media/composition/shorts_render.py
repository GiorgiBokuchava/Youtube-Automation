"""Burn in Shorts-style title + rank/caption overlays (9:16)."""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
from pathlib import Path

from youtube_automation.media.ffmpeg import ensure_ffmpeg
from youtube_automation.media.ffprobe_streams import probe_container_streams


def _ffmpeg_bin() -> str:
    ffmpeg_dir = ensure_ffmpeg()
    return "ffmpeg" if ffmpeg_dir is None else str(Path(ffmpeg_dir) / "ffmpeg")


def _default_font_path() -> Path | None:
    env = os.getenv("SHORTS_FONT_FILE", "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p
    if platform.system() == "Windows":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        for name in ("seguiemj.ttf", "arialbd.ttf", "calibrib.ttf"):
            p = windir / "Fonts" / name
            if p.exists():
                return p
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    ):
        p = Path(candidate)
        if p.exists():
            return p
    return None


def _ffmpeg_path_literal(path: Path) -> str:
    """Path for use inside an ffmpeg filtergraph (escaped colon for Windows drive letters)."""
    s = path.resolve().as_posix()
    return s.replace(":", r"\:")


def render_shorts_segment(
    fitted_video: Path,
    output_video: Path,
    *,
    main_title: str,
    rank: int,
    caption: str,
    font_path: str | Path | None = None,
) -> Path:
    """
    Overlay main title at top and a bottom line `rank. caption` on a 9:16 video.
    Text is supplied via UTF-8 sidecar files for emoji safety.
    """
    font = Path(font_path) if font_path else _default_font_path()
    if font is None:
        raise RuntimeError(
            "No font found for Shorts overlays. Set SHORTS_FONT_FILE to a .ttf path."
        )

    title_txt = (main_title or "").strip()[:90]
    body = f"{int(rank)}. {caption}".strip()[:220]

    output_video.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        title_path = tdir / "title.txt"
        body_path = tdir / "body.txt"
        title_path.write_text(title_txt, encoding="utf-8")
        body_path.write_text(body, encoding="utf-8")

        font_lit = _ffmpeg_path_literal(font)
        title_lit = _ffmpeg_path_literal(title_path)
        body_lit = _ffmpeg_path_literal(body_path)

        graph = (
            f"[0:v]drawtext=fontfile='{font_lit}':textfile='{title_lit}':reload=0:fontsize=46:"
            f"fontcolor=white:x=(w-text_w)/2:y=48:borderw=3:bordercolor=black,"
            f"drawtext=fontfile='{font_lit}':textfile='{body_lit}':reload=0:fontsize=34:"
            f"fontcolor=white:x=32:y=h-200:borderw=3:bordercolor=black[vout]"
        )
        script = tdir / "graph.txt"
        script.write_text(graph, encoding="utf-8")

        cmd: list[str | Path] = [
            _ffmpeg_bin(),
            "-hide_banner",
            "-y",
            "-i",
            str(fitted_video),
            "-filter_complex_script",
            str(script),
            "-map",
            "[vout]",
        ]
        if probe_container_streams(fitted_video).has_audio:
            cmd.extend(["-map", "0:a", "-c:a", "copy"])
        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-movflags",
                "+faststart",
                str(output_video),
            ]
        )
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)

    return output_video
