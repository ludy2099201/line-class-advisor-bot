"""
Session Store — 支援 Redis（生產環境）與 In-Memory（開發環境）雙模式

當環境變數 REDIS_URL 存在時，自動使用 Redis 以支援多實例部署（Railway）。
未設定 REDIS_URL 時，退回 In-Memory 模式，方便本地開發與測試。
"""
import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Session 過期時間（秒），預設 30 分鐘
SESSION_TTL = int(os.environ.get("SESSION_TTL_SECONDS", 1800))


def _get_redis_client():
    """嘗試建立 Redis 連線；失敗時回傳 None。"""
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        return None
    try:
        import redis  # pylint: disable=import-outside-toplevel
        client = redis.from_url(redis_url, decode_responses=True, socket_timeout=3)
        client.ping()
        logger.info("SessionStore: connected to Redis at %s", redis_url.split("@")[-1])
        return client
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("SessionStore: Redis unavailable (%s), falling back to In-Memory.", exc)
        return None


class SessionStore:
    """
    多後端 Session 管理器。

    優先使用 Redis（支援多實例部署）；
    若 Redis 不可用，自動退回 In-Memory 模式（單實例開發用）。
    """

    def __init__(self):
        self._redis = _get_redis_client()
        self._store: Dict[str, Dict[str, Any]] = {}
        mode = "Redis" if self._redis else "In-Memory"
        logger.info("SessionStore initialized in %s mode (TTL=%ds)", mode, SESSION_TTL)

    def get_state(self, user_id: str) -> Optional[str]:
        """取得使用者目前的對話狀態。"""
        session = self._get_session(user_id)
        return session.get("state") if session else None

    def set_state(self, user_id: str, state: str) -> None:
        """設定使用者的對話狀態。"""
        session = self._get_or_create_session(user_id)
        session["state"] = state
        self._save_session(user_id, session)

    def get_data(self, user_id: str, key: str, default: Any = None) -> Any:
        """取得 session 中的特定資料欄位。"""
        session = self._get_session(user_id)
        if session is None:
            return default
        return session.get("data", {}).get(key, default)

    def update_data(self, user_id: str, **kwargs) -> None:
        """更新 session 中的資料欄位（支援多個 key-value）。"""
        session = self._get_or_create_session(user_id)
        session.setdefault("data", {}).update(kwargs)
        self._save_session(user_id, session)

    def clear(self, user_id: str) -> None:
        """清除使用者的 session。"""
        if self._redis:
            try:
                self._redis.delete(self._key(user_id))
                return
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Redis clear error for user %s: %s", user_id, exc)
        self._store.pop(user_id, None)

    @staticmethod
    def _key(user_id: str) -> str:
        return f"session:{user_id}"

    def _get_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        """從 Redis 或 In-Memory 取得 session；過期則回傳 None。"""
        if self._redis:
            try:
                raw = self._redis.get(self._key(user_id))
                return json.loads(raw) if raw else None
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Redis get error for user %s: %s, falling back", user_id, exc)
        session = self._store.get(user_id)
        if session and time.time() > session.get("expires_at", 0):
            del self._store[user_id]
            return None
        return session

    def _get_or_create_session(self, user_id: str) -> Dict[str, Any]:
        """取得或建立 session。"""
        session = self._get_session(user_id)
        if session is None:
            session = {"state": None, "data": {}, "expires_at": time.time() + SESSION_TTL}
        return session

    def _save_session(self, user_id: str, session: Dict[str, Any]) -> None:
        """將 session 寫回 Redis 或 In-Memory。"""
        session["expires_at"] = time.time() + SESSION_TTL
        if self._redis:
            try:
                self._redis.setex(
                    self._key(user_id),
                    SESSION_TTL,
                    json.dumps(session, ensure_ascii=False),
                )
                return
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Redis save error for user %s: %s, falling back", user_id, exc)
        self._store[user_id] = session

    def cleanup_expired(self) -> int:
        """清除 In-Memory 中已過期的 session（Redis 由 TTL 自動處理）。"""
        if self._redis:
            return 0
        now = time.time()
        expired = [uid for uid, s in self._store.items() if now > s.get("expires_at", 0)]
        for uid in expired:
            del self._store[uid]
        if expired:
            logger.debug("Cleaned up %d expired sessions", len(expired))
        return len(expired)
