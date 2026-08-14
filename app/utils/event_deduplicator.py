"""LINE Webhook event 的冪等性去重。"""
import logging
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

EVENT_TTL_SECONDS = 24 * 60 * 60
_MEMORY_EVENTS: Dict[str, float] = {}
_MEMORY_LOCK = threading.Lock()


class EventDeduplicator:
    """
    以 webhookEventId 防止同一 LINE event 的重複 side effect。

    正式環境使用 Redis 的 SET NX EX 原子操作，確保多個 worker 之間共享結果。
    本機開發可使用 process-local memory fallback；正式環境 Redis 異常時回傳 None，
    由呼叫端拒絕處理，避免跨實例重複寫入請假、筆記或通知。
    """

    def __init__(
        self,
        redis_url: str = "",
        ttl_seconds: int = EVENT_TTL_SECONDS,
        allow_memory_fallback: bool = True,
    ):
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self.allow_memory_fallback = allow_memory_fallback
        self._redis = None
        self._redis_init_attempted = False

    def claim(self, event_id: str) -> Optional[bool]:
        """取得事件處理權；新事件為 True，重複事件為 False，故障為 None。"""
        if not event_id:
            return True

        if self.redis_url:
            client = self._get_redis_client()
            if client is not None:
                try:
                    claimed = client.set(
                        self._key(event_id),
                        "1",
                        nx=True,
                        ex=self.ttl_seconds,
                    )
                    return bool(claimed)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Webhook event deduplication failed in Redis: %s", exc)
            if not self.allow_memory_fallback:
                return None

        if self.allow_memory_fallback:
            return self._claim_in_memory(event_id)
        return None

    def _get_redis_client(self):
        """以延遲方式建立 Redis client，避免 app factory 在啟動時阻塞。"""
        if self._redis_init_attempted:
            return self._redis
        self._redis_init_attempted = True

        try:
            import redis  # pylint: disable=import-outside-toplevel

            self._redis = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            return self._redis
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Unable to initialise Redis event deduplicator: %s", exc)
            self._redis = None
            return None

    def release(self, event_id: str) -> None:
        """僅在事件尚未成功入列時釋放 claim，使 LINE 重送可再次安全嘗試。"""
        if not event_id:
            return
        if self.redis_url:
            client = self._get_redis_client()
            if client is not None:
                try:
                    client.delete(self._key(event_id))
                    return
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Unable to release webhook deduplication claim: %s", exc)
        if self.allow_memory_fallback:
            with _MEMORY_LOCK:
                _MEMORY_EVENTS.pop(event_id, None)

    def _claim_in_memory(self, event_id: str) -> bool:
        """開發模式的 thread-safe in-memory 去重與過期清理。"""
        now = time.time()
        with _MEMORY_LOCK:
            expired = [key for key, expiry in _MEMORY_EVENTS.items() if expiry <= now]
            for key in expired:
                del _MEMORY_EVENTS[key]

            if event_id in _MEMORY_EVENTS:
                return False

            _MEMORY_EVENTS[event_id] = now + self.ttl_seconds
            return True

    @staticmethod
    def _key(event_id: str) -> str:
        return f"line:webhook:event:{event_id}"
