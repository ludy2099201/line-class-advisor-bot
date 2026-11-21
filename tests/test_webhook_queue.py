from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import fakeredis
import pytest
from rq import Queue
from rq.serializers import JSONSerializer

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
    fake_queue.connection.pipeline.return_value.__enter__.return_value.exists.return_value = 0
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


def test_webhook_queue_preserves_binary_rq_job_metadata():
    queue = WebhookQueue({"REDIS_URL": "redis://example"})
    connection = MagicMock()
    connection.ping.return_value = True

    with patch("redis.from_url", return_value=connection) as from_url:
        queue._get_queue()

    assert from_url.call_args.kwargs["decode_responses"] is False


@pytest.fixture
def real_queue():
    queue = WebhookQueue({"REDIS_URL": "redis://fake"})
    queue._queue = Queue("webhooks", connection=fakeredis.FakeRedis(), serializer=JSONSerializer)
    return queue


def test_duplicate_event_enqueues_one_job(real_queue):
    event = {"type": "message", "webhookEventId": "same-event"}
    first = real_queue.enqueue_event(event)
    second = real_queue.enqueue_event(event)
    assert first.id == second.id == "line-event-same-event"
    assert real_queue._queue.job_ids == [first.id]
    marker = "line:webhook:job:same-event"
    assert 86399 <= real_queue._queue.connection.ttl(marker) <= 86400


def test_concurrent_duplicate_enqueues_one_job(real_queue):
    event = {"type": "message", "webhookEventId": "concurrent"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = list(pool.map(lambda _: real_queue.enqueue_event(event), range(8)))
    assert {job.id for job in jobs} == {"line-event-concurrent"}
    assert real_queue._queue.count == 1


def test_existing_job_without_marker_is_not_overwritten(real_queue):
    event = {"type": "message", "webhookEventId": "existing", "message": "original"}
    original = real_queue._queue.enqueue(
        "app.webhook_jobs.process_line_event", event, job_id="line-event-existing",
    )
    real_queue.enqueue_event({**event, "message": "redelivery"})
    assert real_queue._queue.count == 1
    assert real_queue._queue.fetch_job(original.id).args[0] == event


def test_marker_prevents_replay_after_finished_job_cleanup(real_queue):
    event = {"type": "message", "webhookEventId": "finished"}
    job = real_queue.enqueue_event(event)
    real_queue._queue.remove(job.id)
    real_queue._queue.connection.delete(job.key)
    assert real_queue.enqueue_event(event) is None
    assert real_queue._queue.count == 0


def test_missing_event_id_still_enqueues_each_event(real_queue):
    event = {"type": "message"}
    first = real_queue.enqueue_event(event)
    second = real_queue.enqueue_event(event)
    assert first.id != second.id
    assert real_queue._queue.count == 2
