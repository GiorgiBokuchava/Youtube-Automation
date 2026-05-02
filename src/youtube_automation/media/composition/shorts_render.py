"""Burn in Shorts-style title + progressive numbered commentary list (9:16)."""

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
        for name in ("arialbd.ttf", "calibrib.ttf", "seguiemj.ttf"):
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


def _default_title_font_path() -> Path | None:
    """Bold / display face for Shorts title (body keeps _default_font_path)."""
    env = os.getenv("SHORTS_TITLE_FONT_FILE", "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p
    if platform.system() == "Windows":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        for name in ("impact.ttf", "arialbd.ttf", "seguiemj.ttf", "calibrib.ttf"):
            p = windir / "Fonts" / name
            if p.exists():
                return p
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    ):
        p = Path(candidate)
        if p.exists():
            return p
    return None


def _ffmpeg_path_literal(path: Path) -> str:
    """Path for use inside an ffmpeg filtergraph (escaped colon for Windows drive letters)."""
    s = path.resolve().as_posix()
    return s.replace(":", r"\:")


def _text_wrap_title(text: str, width: int = 88) -> str:
    import textwrap

    return "\n".join(
        textwrap.wrap((text or "").replace("\n", " ").strip(), width=width)
    )


def render_shorts_segment(
    fitted_video: Path,
    output_video: Path,
    *,
    main_title: str,
    list_lines: list[str],
    font_path: str | Path | None = None,
    title_font_path: str | Path | None = None,
    title_fontcolor: str = "0xffe082",
    title_font_size: int = 58,
    body_font_size: int = 40,
    body_fontcolor: str = "0xfffef8",
    list_margin_x: int = 52,
    title_border_w: int = 4,
    body_border_w: int = 3,
) -> Path:
    """
    Overlay main title at top and one drawtext per list line (left-middle stack).
    No textwrap on list lines - each line is rendered as a single drawtext so line
    numbering stays aligned. UTF-8 sidecar files. Stronger borders/shadows for readability.
    """
    body_font = Path(font_path) if font_path else _default_font_path()
    if body_font is None:
        raise RuntimeError(
            "No font found for Shorts overlays. Set SHORTS_FONT_FILE to a .ttf path."
        )

    title_font: Path | None = None
    if title_font_path:
        tp = Path(title_font_path)
        if tp.exists():
            title_font = tp
    if title_font is None:
        title_font = _default_title_font_path()
    if title_font is None or not title_font.exists():
        title_font = body_font

    title_color = (title_fontcolor or "0xffe082").strip()
    if title_color.startswith("#"):
        title_color = "0x" + title_color[1:]

    body_color = (body_fontcolor or "0xfffef8").strip()
    if body_color.startswith("#"):
        body_color = "0x" + body_color[1:]

    title_txt = _text_wrap_title((main_title or "").strip(), width=88)

    output_video.parent.mkdir(parents=True, exist_ok=True)
    n = len(list_lines)
    line_step = body_font_size + 14

    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        title_path = tdir / "title.txt"
        title_path.write_text(title_txt, encoding="utf-8")

        line_paths: list[Path] = []
        for i, line in enumerate(list_lines):
            p = tdir / f"line_{i}.txt"
            p.write_text(line, encoding="utf-8")
            line_paths.append(p)

        body_font_lit = _ffmpeg_path_literal(body_font)
        title_font_lit = _ffmpeg_path_literal(title_font)
        title_lit = _ffmpeg_path_literal(title_path)

        # Chain: [0:v] title -> [v0] line0 -> [v1] ... -> [vout]
        parts: list[str] = []
        prev = "0:v"
        tag = 0

        parts.append(
            f"[{prev}]drawtext=fontfile='{title_font_lit}':textfile='{title_lit}':reload=0:fontsize={title_font_size}:"
            f"fontcolor={title_color}:x=(w-text_w)/2:y=42:line_spacing=12:box=0:"
            f"borderw={title_border_w}:bordercolor=black@0.94:"
            f"shadowcolor=black@0.90:shadowx=5:shadowy=5[v{tag}]"
        )
        prev = f"v{tag}"
        tag += 1

        for i, lp in enumerate(line_paths):
            lit = _ffmpeg_path_literal(lp)
            out = "vout" if i == n - 1 else f"v{tag}"
            y_expr = f"(h-{line_step}*{n})/2+{line_step}*{i}"
            parts.append(
                f"[{prev}]drawtext=fontfile='{body_font_lit}':textfile='{lit}':reload=0:fontsize={body_font_size}:"
                f"fontcolor={body_color}:x={list_margin_x}:y={y_expr}:line_spacing=0:box=0:"
                f"borderw={body_border_w}:bordercolor=black@0.94:"
                f"shadowcolor=black@0.90:shadowx=4:shadowy=4[{out}]"
            )
            if out != "vout":
                prev = out
                tag += 1

        graph = ";".join(parts)
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
        has_audio = probe_container_streams(fitted_video).has_audio
        if has_audio:
            # Re-encode segment audio so concat stitches cleanly (copy can drift / peak oddly).
            cmd.extend(
                [
                    "-map",
                    "0:a",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-ar",
                    "48000",
                    "-shortest",
                ]
            )
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
