from unittest.mock import MagicMock, patch

from app.services.webhook_queue import WebhookQueue


def test_webhook_queue_defaults_to_no_whole_event_retry():
    queue = WebhookQueue({"REDIS_URL": "redis://example", "WEBHOOK_JOB_MAX_RETRIES": 0})
    assert queue._retry_policy() is None


def test_webhook_queue_builds_explicit_retry_policy_when_enabled():
    queue = WebhookQueue(
        {
            "REDIS_URL": "redis://example",
            "WEBHOOK_JOB_MAX_RETRIES": 2,
            "WEBHOOK_JOB_RETRY_INTERVALS": "10,60,300",
        }
    )
    retry = queue._retry_policy()
    assert retry.max == 2
    assert retry.intervals == [10, 60]


def test_enqueue_uses_json_serializer_and_safe_retention():
    queue = WebhookQueue({"REDIS_URL": "redis://example", "WEBHOOK_JOB_MAX_RETRIES": 0})
    fake_queue = MagicMock()
    fake_queue.enqueue.return_value = MagicMock(id="job-1")
    queue._queue = fake_queue
    event = {"type": "message", "webhookEventId": "evt-1"}
    queue.enqueue_event(event)
    _, kwargs = fake_queue.enqueue.call_args
    assert kwargs["retry"] is None
    assert kwargs["result_ttl"] == 0
    assert kwargs["failure_ttl"] == 24 * 60 * 60


def test_worker_job_creates_router_inside_worker_context():
    event = {"type": "message", "webhookEventId": "evt-job"}
    app = MagicMock()
    app.app_context.return_value.__enter__.return_value = None
    app.app_context.return_value.__exit__.return_value = None
    router = MagicMock()
    with patch("app.create_app", return_value=app), patch("app.webhook_jobs.LineRouter", return_value=router):
        from app.webhook_jobs import process_line_event
        process_line_event(event)
    router.handle.assert_called_once_with(event)
