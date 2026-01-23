import time
import logging
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

from youtube_automation.youtube.auth import load_credentials


def upload_video(
    *,
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    category_id: str,
    privacy_status: str,
    thumbnail_path: Path | None = None,
) -> str:
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

    if thumbnail_path and thumbnail_path.exists():
        try:
            thumbnail_request = yt.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path)),
            )
            _execute_with_retry(thumbnail_request)
        except Exception as e:
            logging.warning(f"Thumbnail upload failed, continuing: {e}")

    return f"https://www.youtube.com/watch?v={video_id}"


def _execute_with_retry(request, max_retries=3):
    """Execute request with exponential backoff retry logic."""
    for attempt in range(max_retries):
        try:
            return request.execute()
        except Exception as e:
            if attempt == max_retries - 1:
                raise e

            # Exponential backoff: 1s, 2s, 4s
            delay = 2**attempt
            logging.warning(
                f"YouTube API request failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay}s..."
            )
            time.sleep(delay)

    raise RuntimeError("All retry attempts failed")
