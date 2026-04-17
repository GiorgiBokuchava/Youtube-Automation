from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from youtube_automation.media.ffmpeg import ffmpeg_bin as _ffmpeg_bin
from youtube_automation.media.ffprobe_streams import (
    ContainerStreamInfo,
    StreamProbeError,
    probe_audio_duration,
    probe_container_streams,
)

logger = logging.getLogger(__name__)

NO_COMMENTARY_HAS_AUDIO = "no_commentary_source_has_audio"
NO_COMMENTARY_NO_AUDIO = "no_commentary_source_no_audio"
COMMENTARY_HAS_AUDIO = "commentary_source_has_audio"
COMMENTARY_NO_AUDIO = "commentary_source_no_audio"


@dataclass(frozen=True)
class RenderClipResult:
    output_path: Path
    path_kind: str


class RenderClipError(RuntimeError):
    """Raised when render preflight, ffmpeg, or output validation fails."""

    def __init__(
        self,
        message: str,
        *,
        command: Optional[list[str]] = None,
        returncode: Optional[int] = None,
        stderr: str = "",
        stdout: str = "",
        stage: str = "ffmpeg",
    ) -> None:
        super().__init__(message)
        self.command = command or []
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout
        self.stage = stage


def _preflight_media_path(path: Path, *, label: str) -> None:
    if not path.exists():
        raise RenderClipError(
            f"{label} does not exist: {path}",
            stage="preflight",
        )
    if path.stat().st_size == 0:
        raise RenderClipError(
            f"{label} is empty: {path}",
            stage="preflight",
        )


def _preflight_input_video(path: Path) -> ContainerStreamInfo:
    _preflight_media_path(path, label="Input video")
    try:
        info = probe_container_streams(path)
    except StreamProbeError as e:
        raise RenderClipError(
            f"Input video probe failed: {e}",
            stage="preflight",
        ) from e
    if not info.has_video:
        raise RenderClipError(
            f"Input video has no video stream: {path}",
            stage="preflight",
        )
    return info


def _preflight_commentary_audio(path: Path) -> None:
    _preflight_media_path(path, label="Commentary audio")
    try:
        info = probe_container_streams(path)
    except StreamProbeError as e:
        raise RenderClipError(
            f"Commentary audio probe failed: {e}",
            stage="preflight",
        ) from e
    if not info.has_audio:
        raise RenderClipError(
            f"Commentary file has no audio stream: {path}",
            stage="preflight",
        )


def _validate_output_file(path: Path) -> None:
    if not path.exists():
        raise RenderClipError(
            f"Expected output missing after ffmpeg: {path}",
            stage="output_validate",
        )
    if path.stat().st_size == 0:
        raise RenderClipError(
            f"Expected output is empty after ffmpeg: {path}",
            stage="output_validate",
        )
    try:
        out_info = probe_container_streams(path)
    except StreamProbeError as e:
        raise RenderClipError(
            f"Output file is not probe-readable: {path}: {e}",
            stage="output_validate",
        ) from e
    if not out_info.has_video:
        raise RenderClipError(
            f"Output has no video stream: {path}",
            stage="output_validate",
        )


def _format_ffmpeg_failure(cmd: list[str], p: subprocess.CompletedProcess[str]) -> str:
    parts = [
        f"ffmpeg exited with code {p.returncode}",
        f"command: {' '.join(cmd)}",
        f"stderr:\n{p.stderr or ''}",
    ]
    if p.stdout:
        parts.append(f"stdout:\n{p.stdout}")
    return "\n".join(parts)


def _run_ffmpeg(cmd: list[str], *, timeout: float = 300.0) -> None:
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if p.returncode != 0:
        raise RenderClipError(
            _format_ffmpeg_failure(cmd, p),
            command=cmd,
            returncode=p.returncode,
            stderr=p.stderr or "",
            stdout=p.stdout or "",
            stage="ffmpeg",
        )


def render_clip(
    *,
    input_video: Path,
    output_video: Path,
    commentary_audio: Optional[Path] = None,
    commentary_offset_sec: float = 0.45,
    original_volume_db: float = 0.0,
    commentary_gain: float = 1.0,
    clip_id: Optional[str] = None,
) -> RenderClipResult:
    """
    Render a single clip with optional commentary. Handles four combinations of
    commentary presence and source audio presence explicitly (no [0:a] unless present).
    """
    output_video.parent.mkdir(parents=True, exist_ok=True)

    src_info = _preflight_input_video(input_video)
    has_source_audio = src_info.has_audio

    use_commentary = bool(commentary_audio and commentary_audio.exists())
    if use_commentary:
        _preflight_commentary_audio(commentary_audio)  # type: ignore[arg-type]

    if use_commentary:
        assert commentary_audio is not None
        delay_ms = int(max(0.0, commentary_offset_sec) * 1000)
        orig_factor = 10 ** (original_volume_db / 20.0)

        if has_source_audio:
            path_kind = COMMENTARY_HAS_AUDIO

            # Build a volume filter that only ducks during the commentary window.
            # Outside that window the original audio plays at full volume.
            # FFmpeg's `enable` expression disables the filter (passes audio unchanged)
            # when the condition is false, so volume=X only applies inside [duck_start,duck_end].
            # Commas inside between() must be escaped as \, in the filter_complex string.
            commentary_dur = probe_audio_duration(commentary_audio)
            if commentary_dur > 0:
                duck_start = max(0.0, commentary_offset_sec)
                duck_end = duck_start + commentary_dur
                vol_filter = (
                    f"volume={orig_factor:.6f}"
                    f":enable=between(t\\,{duck_start:.3f}\\,{duck_end:.3f})"
                )
            else:
                # Probe failed – fall back to flat duck for the whole clip.
                vol_filter = f"volume={orig_factor:.6f}"

            filter_complex = (
                f"[0:v]setpts=PTS-STARTPTS[vout];"
                f"[0:a]{vol_filter},aresample=48000,asetpts=N/SR/TB[a0];"
                f"[1:a]adelay={delay_ms}|{delay_ms},"
                f"volume={commentary_gain},aresample=48000,asetpts=N/SR/TB[a1];"
                f"[a0][a1]amix=inputs=2:weights=1 4:duration=first:dropout_transition=0[aout]"
            )
            cmd = [
                _ffmpeg_bin(),
                "-hide_banner",
                "-y",
                "-i",
                str(input_video),
                "-i",
                str(commentary_audio),
                "-filter_complex",
                filter_complex,
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-r",
                "30",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                str(output_video),
            ]
        else:
            path_kind = COMMENTARY_NO_AUDIO
            filter_complex = (
                f"[0:v]setpts=PTS-STARTPTS[vout];"
                f"[1:a]adelay={delay_ms}|{delay_ms},"
                f"volume={commentary_gain},"
                f"aresample=48000,asetpts=N/SR/TB[aout]"
            )
            cmd = [
                _ffmpeg_bin(),
                "-hide_banner",
                "-y",
                "-i",
                str(input_video),
                "-i",
                str(commentary_audio),
                "-filter_complex",
                filter_complex,
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-r",
                "30",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                str(output_video),
            ]
    else:
        # No voiceover — pass original audio at full volume regardless of the
        # duck setting (original_volume_db is only meaningful when a commentary
        # track is competing for headroom over the source audio).
        if has_source_audio:
            path_kind = NO_COMMENTARY_HAS_AUDIO
            filter_complex = (
                "[0:v]setpts=PTS-STARTPTS[vout];"
                "[0:a]aresample=48000,asetpts=N/SR/TB[aout]"
            )
            cmd = [
                _ffmpeg_bin(),
                "-hide_banner",
                "-y",
                "-i",
                str(input_video),
                "-filter_complex",
                filter_complex,
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-r",
                "30",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                str(output_video),
            ]
        else:
            path_kind = NO_COMMENTARY_NO_AUDIO
            cmd = [
                _ffmpeg_bin(),
                "-hide_banner",
                "-y",
                "-i",
                str(input_video),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-vf",
                "setpts=PTS-STARTPTS",
                "-map",
                "0:v:0",
                "-map",
                "1:a",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-r",
                "30",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-shortest",
                str(output_video),
            ]

    ctx = clip_id or input_video.name
    logger.info(
        "render_clip clip=%s path_kind=%s source_has_audio=%s commentary=%s -> %s",
        ctx,
        path_kind,
        has_source_audio,
        use_commentary,
        output_video,
    )

    try:
        _run_ffmpeg(cmd, timeout=300.0)
    except subprocess.TimeoutExpired as e:
        raise RenderClipError(
            f"ffmpeg timed out after {e.timeout}s",
            command=cmd,
            stage="ffmpeg",
        ) from e

    _validate_output_file(output_video)

    return RenderClipResult(output_path=output_video, path_kind=path_kind)
