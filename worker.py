"""Railway 獨立 service 的 LINE webhook RQ worker 入口。"""
import logging

from rq import Queue, Worker
from rq.serializers import JSONSerializer

from app.config import Config
from app.webhook_jobs import audit_job_exception

logger = logging.getLogger(__name__)


def main() -> None:
    if not Config.REDIS_URL:
        raise RuntimeError("REDIS_URL is required for the LINE webhook worker")

    import redis  # pylint: disable=import-outside-toplevel

    # RQ job metadata 可能含壓縮二進位資料；必須保留 bytes，避免
    # redis-py 在 worker 讀取 job hash 前發生 UnicodeDecodeError。
    connection = redis.from_url(
        Config.REDIS_URL,
        decode_responses=False,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
    connection.ping()
    queue = Queue(Config.WEBHOOK_QUEUE_NAME, connection=connection, serializer=JSONSerializer)
    worker = Worker(
        [queue],
        connection=connection,
        serializer=JSONSerializer,
        exception_handlers=[audit_job_exception],
    )
    logger.info(
        "Starting LINE webhook worker | queue=%s retries_default=%s",
        Config.WEBHOOK_QUEUE_NAME,
        Config.WEBHOOK_JOB_MAX_RETRIES,
    )
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
