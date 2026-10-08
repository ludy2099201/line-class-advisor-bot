"""RQ worker 執行的 webhook 工作函式。"""
import logging
from typing import Any, Dict, Optional

from flask import Flask

from .handlers.router import LineRouter
from .utils.security import audit_event, short_hash

logger = logging.getLogger(__name__)

# worker process 內重用同一個 Flask app，避免每個 event 重建 app、
# Redis 去重與 queue 元件；每個 job 仍建立新的 LineRouter 以取得最新 Notion 對應。
# RQ 預設為每個 job fork 子程序，因此 worker.py 會在 fork 前先呼叫 get_worker_app() 預熱。
_APP: Optional[Flask] = None


def get_worker_app() -> Flask:
    """取得（必要時建立）worker 共用的 Flask app；Redis 連線皆為延遲建立，可安全 fork。"""
    global _APP  # pylint: disable=global-statement
    if _APP is None:
        from . import create_app  # 避免 worker import 與 Flask app factory 循環依賴。

        _APP = create_app()
    return _APP


def process_line_event(event: Dict[str, Any]) -> None:
    """在 worker process 內處理已驗簽且已去重的單一 LINE event。"""
    app = get_worker_app()
    event_type = event.get("type", "unknown")
    event_id = event.get("webhookEventId", "")
    with app.app_context():
        try:
            LineRouter(app.config).handle(event)
            logger.info(
                "Webhook job completed | event_hash=%s type=%s",
                short_hash(event_id),
                event_type,
            )
        except Exception as exc:  # pylint: disable=broad-except
            _audit_job_failure(event_type, event_id, type(exc).__name__)
            raise


def audit_job_exception(job, exc_type, exc_value, traceback):  # pylint: disable=unused-argument
    """RQ failure hook：不記錄 traceback 或原始 event，只留下可用的隔離審計訊號。"""
    event = (job.args or [{}])[0] if getattr(job, "args", None) else {}
    event_type = event.get("type", "unknown") if isinstance(event, dict) else "unknown"
    event_id = event.get("webhookEventId", "") if isinstance(event, dict) else ""
    retries_left = getattr(job, "retries_left", 0) or 0
    outcome = "retry_scheduled" if retries_left > 0 else "dead_lettered"
    audit_event("webhook_job", outcome)
    logger.warning(
        "Webhook job failed | job_id=%s event_hash=%s type=%s outcome=%s exception_type=%s",
        getattr(job, "id", ""),
        short_hash(event_id),
        event_type,
        outcome,
        getattr(exc_type, "__name__", "UnknownError"),
    )
    return True


def _audit_job_failure(event_type: str, event_id: str, exception_type: str) -> None:
    """在 job 內先記錄最小化失敗訊號，RQ handler 會補上隔離結果。"""
    logger.warning(
        "Webhook job raised | event_hash=%s type=%s exception_type=%s",
        short_hash(event_id),
        event_type,
        exception_type,
    )
