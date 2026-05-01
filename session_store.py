"""
簡易 In-Memory Session Store
用於管理私訊多輪對話狀態（例如請假流程）。
生產環境建議替換為 Redis 或 PostgreSQL 以支援多實例部署。
"""
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Session 過期時間（秒），預設 30 分鐘
SESSION_TTL = 1800


class SessionStore:
    """輕量級 In-Memory Session 管理器。"""

    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}

    def get_state(self, user_id: str) -> Optional[str]:
        """取得使用者目前的對話狀態。"""
        session = self._get_session(user_id)
        if session is None:
            return None
        return session.get("state")

    def set_state(self, user_id: str, state: str, data: Optional[Dict] = None) -> None:
        """設定使用者的對話狀態，並可選擇性初始化資料。"""
        session = self._get_or_create_session(user_id)
        session["state"] = state
        session["updated_at"] = time.time()
        if data is not None:
            session["data"] = data

    def get_data(self, user_id: str) -> Dict[str, Any]:
        """取得使用者的對話資料。"""
        session = self._get_session(user_id)
        if session is None:
            return {}
        return session.get("data", {})

    def update_data(self, user_id: str, updates: Dict[str, Any]) -> None:
        """更新使用者的對話資料（合併更新）。"""
        session = self._get_or_create_session(user_id)
        session.setdefault("data", {}).update(updates)
        session["updated_at"] = time.time()

    def clear(self, user_id: str) -> None:
        """清除使用者的 Session。"""
        self._store.pop(user_id, None)
        logger.debug("Session cleared for user: %s...", user_id[:8])

    def _get_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        """取得 Session，若已過期則自動清除。"""
        session = self._store.get(user_id)
        if session is None:
            return None
        # 檢查是否過期
        if time.time() - session.get("updated_at", 0) > SESSION_TTL:
            self.clear(user_id)
            return None
        return session

    def _get_or_create_session(self, user_id: str) -> Dict[str, Any]:
        """取得或建立 Session。"""
        session = self._get_session(user_id)
        if session is None:
            session = {
                "state": None,
                "data": {},
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            self._store[user_id] = session
        return session

    def cleanup_expired(self) -> int:
        """清除所有過期 Session，回傳清除數量。"""
        now = time.time()
        expired = [
            uid
            for uid, s in self._store.items()
            if now - s.get("updated_at", 0) > SESSION_TTL
        ]
        for uid in expired:
            del self._store[uid]
        if expired:
            logger.info("Cleaned up %d expired sessions", len(expired))
        return len(expired)
