"""LINE webhook 背景工作 queue；web service 只驗簽、去重並安全入列。"""
import logging
from typing import Any, Dict, Optional

from rq import Queue, Retry
from rq.serializers import JSONSerializer

logger = logging.getLogger(__name__)

JOB_FAILURE_TTL_SECONDS = 24 * 60 * 60


class WebhookQueueUnavailable(RuntimeError):
    """Redis／RQ queue 無法安全使用時拋出。"""


class WebhookQueue:
    """以 Railway Redis 為後端的 LINE webhook queue。"""

    def __init__(self, config: Dict[str, Any]):
        self.redis_url = config.get("REDIS_URL", "")
        self.name = config.get("WEBHOOK_QUEUE_NAME", "line_webhooks")
        self.timeout = int(config.get("WEBHOOK_JOB_TIMEOUT_SECONDS", 120))
        self.max_retries = int(config.get("WEBHOOK_JOB_MAX_RETRIES", 0))
        self.retry_intervals = self._parse_intervals(
            config.get("WEBHOOK_JOB_RETRY_INTERVALS", "10,60,300")
        )
        self._queue: Optional[Queue] = None

    def enqueue_event(self, event: Dict[str, Any]):
        """將單一已驗簽 event 入列；僅傳送 event，不傳送 secrets 或 app config。"""
        queue = self._get_queue()
        retry = self._retry_policy()
        try:
            job = queue.enqueue(
                "app.webhook_jobs.process_line_event",
                event,
                job_timeout=self.timeout,
                retry=retry,
                result_ttl=0,
                failure_ttl=JOB_FAILURE_TTL_SECONDS,
            )
        except Exception as exc:  # pylint: disable=broad-except
            raise WebhookQueueUnavailable("Unable to enqueue LINE webhook event") from exc
        logger.info(
            "LINE webhook event enqueued | job_id=%s event_id=%s type=%s",
            job.id,
            event.get("webhookEventId", ""),
            event.get("type", "unknown"),
        )
        return job

    def _get_queue(self) -> Queue:
        if self._queue is not None:
            return self._queue
        if not self.redis_url:
            raise WebhookQueueUnavailable("REDIS_URL is not configured")
        try:
            import redis  # pylint: disable=import-outside-toplevel

            connection = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            connection.ping()
            self._queue = Queue(self.name, connection=connection, serializer=JSONSerializer)
            return self._queue
        except Exception as exc:  # pylint: disable=broad-except
            raise WebhookQueueUnavailable("Redis-backed webhook queue is unavailable") from exc

    def _retry_policy(self):
        """整個 webhook event 預設不重試，避免重複的 LINE／Notion side effect。"""
        if self.max_retries <= 0:
            return None
        intervals = self.retry_intervals[: self.max_retries]
        if len(intervals) < self.max_retries:
            intervals += [intervals[-1] if intervals else 60] * (self.max_retries - len(intervals))
        return Retry(max=self.max_retries, interval=intervals)

    @staticmethod
    def _parse_intervals(value: str) -> list[int]:
        intervals = []
        for item in str(value).split(","):
            try:
                parsed = int(item.strip())
                if parsed >= 0:
                    intervals.append(parsed)
            except ValueError:
                continue
        return intervals or [10, 60, 300]
