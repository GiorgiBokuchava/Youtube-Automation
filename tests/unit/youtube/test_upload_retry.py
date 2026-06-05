import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from youtube_automation.youtube import upload as upload_mod
from youtube_automation.youtube.upload import UploadResult, thumbnail_retryable_http_error


def _http_error(status: int, reason: str = "error") -> HttpError:
    resp = type("Resp", (), {"status": status, "reason": reason})()
    return HttpError(resp=resp, content=reason.encode())


def test_execute_with_retry_no_retry_on_refresh_error(mocker):
    request = mocker.Mock()
    request.execute.side_effect = RefreshError("invalid_grant")

    with pytest.raises(RefreshError):
        upload_mod._execute_with_retry(request, max_retries=3)

    assert request.execute.call_count == 1


@pytest.mark.parametrize(
    "status,expected",
    [
        (404, True),
        (429, True),
        (500, True),
        (403, False),
        (400, False),
    ],
)
def test_thumbnail_retryable_http_error(status: int, expected: bool) -> None:
    assert thumbnail_retryable_http_error(_http_error(status)) is expected


def test_upload_thumbnail_retries_on_404(mocker, tmp_path):
    thumb = tmp_path / "t.jpg"
    thumb.write_bytes(b"\xff\xd8\xff" + b"x" * 100)

    mocker.patch("youtube_automation.youtube.upload.time.sleep")
    mocker.patch(
        "youtube_automation.youtube.upload._validate_thumbnail_dimensions",
        return_value=True,
    )

    yt = mocker.Mock()
    request = mocker.Mock()
    request.execute.side_effect = [
        _http_error(404, "videoNotFound"),
        {"items": []},
    ]
    yt.thumbnails.return_value.set.return_value = request

    ok = upload_mod.upload_thumbnail(yt, "abc123", thumb, max_attempts=2)

    assert ok is True
    assert request.execute.call_count == 2


def test_upload_thumbnail_403_does_not_retry(mocker, tmp_path):
    thumb = tmp_path / "t.jpg"
    thumb.write_bytes(b"\xff\xd8\xff" + b"x" * 100)

    mocker.patch("youtube_automation.youtube.upload.time.sleep")
    mocker.patch(
        "youtube_automation.youtube.upload._validate_thumbnail_dimensions",
        return_value=True,
    )

    yt = mocker.Mock()
    request = mocker.Mock()
    request.execute.side_effect = _http_error(403, "forbidden")
    yt.thumbnails.return_value.set.return_value = request

    ok = upload_mod.upload_thumbnail(yt, "abc123", thumb, max_attempts=3)

    assert ok is False
    assert request.execute.call_count == 1


def test_upload_video_returns_thumbnail_set_flag(mocker, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    thumb = tmp_path / "t.jpg"
    thumb.write_bytes(b"\xff\xd8\xff" + b"x" * 100)

    mocker.patch("youtube_automation.youtube.upload.load_credentials")
    mocker.patch("youtube_automation.youtube.upload.build", return_value=mocker.Mock())

    insert_request = mocker.Mock()
    insert_request.execute.return_value = {"id": "vid1"}
    mocker.patch(
        "youtube_automation.youtube.upload._execute_with_retry",
        return_value={"id": "vid1"},
    )
    mocker.patch(
        "youtube_automation.youtube.upload.upload_thumbnail",
        return_value=True,
    )

    yt = upload_mod.build.return_value
    yt.videos.return_value.insert.return_value = insert_request

    result = upload_mod.upload_video(
        video_path=video,
        title="t",
        description="d",
        tags=[],
        category_id="2",
        privacy_status="unlisted",
        thumbnail_path=thumb,
    )

    assert result == UploadResult(
        url="https://www.youtube.com/watch?v=vid1", thumbnail_set=True
    )
