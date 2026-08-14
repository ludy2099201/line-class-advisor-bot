"""只快取低敏感 FAQ 與班級清單，禁止用於學生或群組識別資料。"""
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_MEMORY_CACHE: Dict[str, tuple[float, Any]] = {}
_MEMORY_LOCK = threading.Lock()


class LowSensitivityCache:
    """Redis 優先、開發環境記憶體後備的 JSON 快取。"""

    def __init__(self, redis_url: str = "", allow_memory_fallback: bool = True):
        self.redis_url = redis_url
        self.allow_memory_fallback = allow_memory_fallback
        self._redis = None
        self._redis_init_attempted = False

    def get_or_load(self, key: str, ttl_seconds: int, loader: Callable[[], Any]) -> Any:
        value = self._get(key)
        if value is not None:
            return value
        value = loader()
        self._set(key, value, ttl_seconds)
        return value

    def _get(self, key: str) -> Optional[Any]:
        client = self._get_redis_client()
        if client is not None:
            try:
                raw = client.get(key)
                return json.loads(raw) if raw else None
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Low-sensitivity cache Redis get failed: %s", exc)
        if not self.allow_memory_fallback:
            return None
        with _MEMORY_LOCK:
            item = _MEMORY_CACHE.get(key)
            if not item or item[0] <= time.time():
                _MEMORY_CACHE.pop(key, None)
                return None
            return item[1]

    def _set(self, key: str, value: Any, ttl_seconds: int) -> None:
        ttl_seconds = max(1, int(ttl_seconds))
        client = self._get_redis_client()
        if client is not None:
            try:
                client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
                return
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Low-sensitivity cache Redis set failed: %s", exc)
        if self.allow_memory_fallback:
            with _MEMORY_LOCK:
                _MEMORY_CACHE[key] = (time.time() + ttl_seconds, value)

    def _get_redis_client(self):
        if self._redis_init_attempted:
            return self._redis
        self._redis_init_attempted = True
        if not self.redis_url:
            return None
        try:
            import redis  # pylint: disable=import-outside-toplevel

            self._redis = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Unable to initialise low-sensitivity cache Redis: %s", exc)
            self._redis = None
        return self._redis
