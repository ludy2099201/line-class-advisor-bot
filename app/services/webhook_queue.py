"""LINE webhook 背景工作 queue；web service 只驗簽、去重並安全入列。"""
import logging
from typing import Any, Dict, Optional

from redis.exceptions import WatchError
from rq import Queue, Retry
from rq.job import Job
from rq.serializers import JSONSerializer

logger = logging.getLogger(__name__)

JOB_FAILURE_TTL_SECONDS = 24 * 60 * 60
JOB_DEDUP_TTL_SECONDS = 24 * 60 * 60


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
            options = dict(job_timeout=self.timeout, retry=retry, result_ttl=0,
                           failure_ttl=JOB_FAILURE_TTL_SECONDS)
            event_id = event.get("webhookEventId", "")
            if event_id:
                job = self._enqueue_once(queue, event, event_id, options)
            else:
                job = queue.enqueue("app.webhook_jobs.process_line_event", event, **options)
        except Exception as exc:  # pylint: disable=broad-except
            raise WebhookQueueUnavailable("Unable to enqueue LINE webhook event") from exc
        logger.info(
            "LINE webhook event enqueued | job_id=%s event_id=%s type=%s",
            job.id if job is not None else "already_processed",
            event.get("webhookEventId", ""),
            event.get("type", "unknown"),
        )
        return job

    @staticmethod
    def _enqueue_once(queue, event, event_id, options):
        """Atomically guard enqueue; RQ alone overwrites jobs with reused IDs.

        Keep a payload-free marker after result_ttl=0 removes completed jobs.
        WATCH also protects against concurrent callers and ambiguous enqueue replies.
        """
        job_id = f"line-event-{event_id}"
        marker = f"line:webhook:job:{event_id}"
        while True:
            with queue.connection.pipeline() as pipe:
                try:
                    pipe.watch(marker, Job.key_for(job_id))
                    if pipe.exists(marker) or Job.exists(job_id, connection=pipe):
                        logger.info("Duplicate webhook job enqueue ignored | job_id=%s", job_id)
                        return queue.fetch_job(job_id)
                    pipe.multi()
                    job = queue.enqueue(
                        "app.webhook_jobs.process_line_event", event,
                        job_id=job_id, pipeline=pipe, **options,
                    )
                    pipe.set(marker, "1", ex=JOB_DEDUP_TTL_SECONDS)
                    pipe.execute()
                    return job
                except WatchError:
                    continue

    def _get_queue(self) -> Queue:
        if self._queue is not None:
            return self._queue
        if not self.redis_url:
            raise WebhookQueueUnavailable("REDIS_URL is not configured")
        try:
            import redis  # pylint: disable=import-outside-toplevel

            # RQ 在 job hash 內使用壓縮的二進位 metadata；不可讓 redis-py
            # 在 RQ 取用前以 UTF-8 解碼，否則 worker 無法讀取已入列工作。
            connection = redis.from_url(
                self.redis_url,
                decode_responses=False,
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
