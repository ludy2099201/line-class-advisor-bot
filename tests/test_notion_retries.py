"""Notion 唯讀查詢的限流與受控重試測試。"""
from unittest.mock import MagicMock, patch

from app.services.notion_service import NotionService


def _response(status_code: int, payload=None, text: str = "", headers=None):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.headers = headers or {}
    response.json.return_value = payload or {}
    return response


def _service() -> NotionService:
    return NotionService(
        {
            "NOTION_API_TOKEN": "test-token",
            "NOTION_DB_FAQ": "db-faq",
        }
    )


def test_query_retries_rate_limit_then_returns_results():
    service = _service()
    rate_limited = _response(429, text="rate_limited", headers={"Retry-After": "2"})
    success = _response(200, payload={"results": [{"id": "page-1"}]})

    with patch(
        "app.services.notion_service.requests.post", side_effect=[rate_limited, success]
    ) as post, patch("app.services.notion_service.time.sleep") as sleep, patch(
        "app.services.notion_service.random.uniform", return_value=0
    ):
        results = service._query_database("db-faq", {"page_size": 1})

    assert results == [{"id": "page-1"}]
    assert post.call_count == 2
    sleep.assert_called_once_with(2)


def test_query_does_not_retry_invalid_request():
    service = _service()
    invalid = _response(400, text="validation_error")

    with patch("app.services.notion_service.requests.post", return_value=invalid) as post, \
         patch("app.services.notion_service.time.sleep") as sleep:
        results = service._query_database("db-faq", {"bad": "payload"})

    assert results == []
    assert post.call_count == 1
    sleep.assert_not_called()
