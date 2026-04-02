import pytest
from google.auth.exceptions import RefreshError

from youtube_automation.youtube import upload as upload_mod


def test_execute_with_retry_no_retry_on_refresh_error(mocker):
    request = mocker.Mock()
    request.execute.side_effect = RefreshError("invalid_grant")

    with pytest.raises(RefreshError):
        upload_mod._execute_with_retry(request, max_retries=3)

    assert request.execute.call_count == 1
