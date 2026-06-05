from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from youtube_automation.youtube.auth import load_credentials

logger = logging.getLogger(__name__)

THUMBNAIL_MAX_BYTES = 2 * 1024 * 1024
# YouTube often rejects thumbnails.set until the video is indexed (404 / processing).
THUMBNAIL_INITIAL_DELAY_SEC = 3
THUMBNAIL_RETRY_DELAYS_SEC = (5, 10, 20, 30)
THUMBNAIL_MIN_WIDTH = 640
THUMBNAIL_MIN_HEIGHT = 360


@dataclass(frozen=True)
class UploadResult:
    url: str
    thumbnail_set: bool


def resolve_thumbnail_path(thumbnail_path: Path | None) -> Path | None:
    """Resolve thumbnail path; return None if missing (never log file contents)."""
    if thumbnail_path is None:
        return None
    path = thumbnail_path.expanduser().resolve()
    if not path.is_file():
        logger.warning("Thumbnail file not found at upload time: %s", path)
        return None
    size = path.stat().st_size
    if size > THUMBNAIL_MAX_BYTES:
        logger.warning(
            "Thumbnail too large for YouTube (%d bytes > %d): %s",
            size,
            THUMBNAIL_MAX_BYTES,
            path.name,
        )
        return None
    return path


def thumbnail_retryable_http_error(error: HttpError) -> bool:
    """True when re-trying thumbnails.set may succeed (processing lag, rate limits)."""
    status = getattr(getattr(error, "resp", None), "status", None)
    if status in (429, 500, 502, 503):
        return True
    if status == 404:
        return True
    return False


def _format_http_error(error: HttpError) -> str:
    status = getattr(getattr(error, "resp", None), "status", None)
    reason = getattr(error, "reason", None) or str(error)
    return f"HTTP {status}: {reason}"


def _validate_thumbnail_dimensions(path: Path) -> bool:
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
    except Exception as e:
        logger.warning("Could not read thumbnail dimensions for %s: %s", path.name, e)
        return True
    if w < THUMBNAIL_MIN_WIDTH or h < THUMBNAIL_MIN_HEIGHT:
        logger.warning(
            "Thumbnail below YouTube minimum (%dx%d, need >=%dx%d): %s",
            w,
            h,
            THUMBNAIL_MIN_WIDTH,
            THUMBNAIL_MIN_HEIGHT,
            path.name,
        )
        return False
    return True


def upload_thumbnail(
    yt,
    video_id: str,
    thumbnail_path: Path,
    *,
    max_attempts: int | None = None,
) -> bool:
    """
    Set custom thumbnail with waits/retries for post-upload processing lag.

    Returns True on success. Does not raise on failure (caller logs/records).
    """
    path = resolve_thumbnail_path(thumbnail_path)
    if path is None:
        return False

    if not _validate_thumbnail_dimensions(path):
        return False

    delays = [THUMBNAIL_INITIAL_DELAY_SEC, *THUMBNAIL_RETRY_DELAYS_SEC]
    if max_attempts is not None:
        delays = delays[:max_attempts]

    last_error: Exception | None = None
    for attempt, delay in enumerate(delays, start=1):
        if delay > 0:
            logger.info(
                "Thumbnail upload attempt %d/%d for video %s (wait %ds)",
                attempt,
                len(delays),
                video_id,
                delay,
            )
            time.sleep(delay)
        try:
            request = yt.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(
                    str(path),
                    mimetype="image/jpeg",
                    resumable=False,
                ),
            )
            _execute_with_retry(request)
            logger.info("Custom thumbnail set for video %s (%s)", video_id, path.name)
            return True
        except HttpError as e:
            last_error = e
            detail = _format_http_error(e)
            if thumbnail_retryable_http_error(e) and attempt < len(delays):
                logger.warning(
                    "Thumbnail upload attempt %d failed (%s), retrying…",
                    attempt,
                    detail,
                )
                continue
            status = getattr(getattr(e, "resp", None), "status", None)
            if status == 403:
                logger.error(
                    "Thumbnail upload forbidden for video %s. Common causes: channel "
                    "not verified for custom thumbnails (verify phone in YouTube Studio), "
                    "or OAuth token lacks youtube.upload scope. %s",
                    video_id,
                    detail,
                )
            else:
                logger.error(
                    "Thumbnail upload failed for video %s after %d attempt(s): %s",
                    video_id,
                    attempt,
                    detail,
                )
            return False
        except Exception as e:
            last_error = e
            logger.error(
                "Thumbnail upload failed for video %s: %s: %s",
                video_id,
                type(e).__name__,
                e,
            )
            return False

    if last_error is not None:
        logger.error("Thumbnail upload exhausted retries for video %s", video_id)
    return False


def upload_video(
    *,
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    category_id: str,
    privacy_status: str,
    thumbnail_path: Path | None = None,
) -> UploadResult:
    creds = load_credentials()
    yt = build("youtube", "v3", credentials=creds)

    request = yt.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
            },
        },
        media_body=MediaFileUpload(
            str(video_path),
            chunksize=-1,
            resumable=True,
        ),
    )

    response = _execute_with_retry(request)
    video_id = response["id"]
    url = f"https://www.youtube.com/watch?v={video_id}"

    thumbnail_set = False
    if thumbnail_path is not None:
        thumbnail_set = upload_thumbnail(yt, video_id, thumbnail_path)
    else:
        logger.info("No thumbnail path provided; skipping custom thumbnail upload")

    return UploadResult(url=url, thumbnail_set=thumbnail_set)


def _execute_with_retry(request, max_retries=3):
    """Execute request with exponential backoff for transient failures only."""
    for attempt in range(max_retries):
        try:
            return request.execute()
        except RefreshError:
            raise
        except HttpError as e:
            status = getattr(getattr(e, "resp", None), "status", None)
            if status is not None and 400 <= status < 500 and status != 429:
                raise
            if attempt == max_retries - 1:
                raise
            delay = 2**attempt
            logger.warning(
                "YouTube API request failed (attempt %s/%s): %s. Retrying in %ss...",
                attempt + 1,
                max_retries,
                e,
                delay,
            )
            time.sleep(delay)
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            delay = 2**attempt
            logger.warning(
                "YouTube API request failed (attempt %s/%s): %s. Retrying in %ss...",
                attempt + 1,
                max_retries,
                e,
                delay,
            )
            time.sleep(delay)

    raise RuntimeError("All retry attempts failed")
