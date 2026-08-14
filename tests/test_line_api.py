"""LINE API 受控重試與冪等性測試。"""
from unittest.mock import MagicMock, patch

from app.services.line_api import LineApiService


def _response(status_code: int, text: str = "", headers=None):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.headers = headers or {}
    return response


def _service() -> LineApiService:
    return LineApiService({"LINE_CHANNEL_ACCESS_TOKEN": "test-token"})


def test_push_retries_5xx_with_same_retry_key():
    service = _service()
    first = _response(500, "temporary error", {"x-line-request-id": "request-1"})
    second = _response(200, headers={"x-line-request-id": "request-2"})

    with patch("app.services.line_api.requests.post", side_effect=[first, second]) as post, \
         patch.object(service, "_sleep_before_retry") as sleep:
        accepted = service.push_message("U_test", "重要提醒", retry_key="retry-key-1")

    assert accepted is True
    assert post.call_count == 2
    assert sleep.call_count == 1
    assert post.call_args_list[0].kwargs["headers"]["X-Line-Retry-Key"] == "retry-key-1"
    assert post.call_args_list[1].kwargs["headers"]["X-Line-Retry-Key"] == "retry-key-1"


def test_push_409_means_prior_request_was_accepted():
    service = _service()
    response = _response(
        409,
        "already accepted",
        {
            "x-line-request-id": "request-2",
            "x-line-accepted-request-id": "request-1",
        },
    )

    with patch("app.services.line_api.requests.post", return_value=response) as post:
        accepted = service.push_message("U_test", "重要提醒", retry_key="retry-key-2")

    assert accepted is True
    assert post.call_count == 1


def test_push_does_not_retry_client_error():
    service = _service()
    response = _response(400, "invalid request", {"x-line-request-id": "request-3"})

    with patch("app.services.line_api.requests.post", return_value=response) as post, \
         patch.object(service, "_sleep_before_retry") as sleep:
        accepted = service.push_message("U_test", "重要提醒", retry_key="retry-key-3")

    assert accepted is False
    assert post.call_count == 1
    sleep.assert_not_called()
