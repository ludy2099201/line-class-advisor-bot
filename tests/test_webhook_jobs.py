"""webhook worker job 的 app 重用與 session 政策測試。"""
from unittest.mock import MagicMock, patch

from app import webhook_jobs
from app.handlers.router import LineRouter


def test_process_line_event_reuses_one_app_across_jobs(monkeypatch, app):
    monkeypatch.setattr(webhook_jobs, "_APP", None)
    with patch("app.create_app", return_value=app) as mock_create, \
         patch("app.webhook_jobs.LineRouter") as mock_router:
        webhook_jobs.process_line_event({"type": "message", "webhookEventId": "e1"})
        webhook_jobs.process_line_event({"type": "message", "webhookEventId": "e2"})

    mock_create.assert_called_once()
    assert mock_router.return_value.handle.call_count == 2


def _build_router(app_env: str) -> MagicMock:
    with patch("app.handlers.router.LineApiService"), \
         patch("app.handlers.router.NotionService"), \
         patch("app.handlers.router.SessionStore") as mock_store:
        LineRouter({"APP_ENV": app_env})
    return mock_store


def test_router_disallows_memory_session_fallback_in_production():
    _build_router("production").assert_called_once_with(allow_memory_fallback=False)


def test_router_allows_memory_session_fallback_in_development():
    _build_router("development").assert_called_once_with(allow_memory_fallback=True)


def test_leave_handler_shares_router_session_store():
    with patch("app.handlers.router.LineApiService"), \
         patch("app.handlers.router.NotionService"), \
         patch("app.handlers.router.SessionStore"):
        router = LineRouter({"APP_ENV": "development"})

    assert router.leave_handler.session is router.session
