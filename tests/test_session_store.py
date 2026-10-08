"""SessionStore 單元測試。"""
import time
from unittest.mock import MagicMock

import pytest

from app.utils import session_store as session_store_module
from app.utils.session_store import SESSION_TTL, SessionStore


@pytest.fixture
def store(monkeypatch):
    """強制使用 In-Memory 後端，避免測試依賴外部 Redis。"""
    monkeypatch.delenv("REDIS_URL", raising=False)
    return SessionStore()


class TestSessionStore:
    """測試多輪對話狀態、資料與 TTL 管理。"""

    def test_initial_state_is_none(self, store):
        assert store.get_state("user_1") is None

    def test_set_and_get_state(self, store):
        store.set_state("user_1", "leave_wait_name")

        assert store.get_state("user_1") == "leave_wait_name"

    def test_update_and_get_data(self, store):
        store.set_state("user_1", "leave_wait_date")
        store.update_data("user_1", student_name="王小明", leave_date="05/10")

        assert store.get_data("user_1", "student_name") == "王小明"
        assert store.get_data("user_1", "leave_date") == "05/10"

    def test_clear_session(self, store):
        store.set_state("user_1", "some_state")
        store.clear("user_1")

        assert store.get_state("user_1") is None

    def test_expired_session_returns_none(self, store):
        store.set_state("user_1", "leave_wait_name")
        store._store["user_1"]["expires_at"] = time.time() - SESSION_TTL - 1

        assert store.get_state("user_1") is None

    def test_cleanup_expired(self, store):
        store.set_state("user_1", "state_a")
        store.set_state("user_2", "state_b")
        store._store["user_1"]["expires_at"] = time.time() - SESSION_TTL - 1

        count = store.cleanup_expired()

        assert count == 1
        assert store.get_state("user_1") is None
        assert store.get_state("user_2") == "state_b"

    def test_raw_key_value_uses_ttl_aware_storage(self, store):
        store.set("bind:group_1", {"state": "selecting"})

        assert store.get("bind:group_1") == {"state": "selecting"}

        store.delete("bind:group_1")
        assert store.get("bind:group_1") is None


class TestSessionStoreFailClosed:
    """production 不允許 session 退回 instance-local memory。

    test_config 會 reload session_store，故一律經由 module 屬性取得目前的類別。
    """

    def test_raises_when_redis_missing_and_fallback_disallowed(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)

        with pytest.raises(session_store_module.SessionStoreUnavailable):
            session_store_module.SessionStore(allow_memory_fallback=False)

    def test_raises_on_redis_error_instead_of_writing_memory(self, monkeypatch):
        failing_redis = MagicMock()
        failing_redis.setex.side_effect = ConnectionError("redis down")
        failing_redis.get.side_effect = ConnectionError("redis down")
        monkeypatch.setattr(
            "app.utils.session_store._get_redis_client", lambda: failing_redis
        )
        store = session_store_module.SessionStore(allow_memory_fallback=False)

        with pytest.raises(session_store_module.SessionStoreUnavailable):
            store.set("bind_C1", {"bind_state": "selecting"})
        with pytest.raises(session_store_module.SessionStoreUnavailable):
            store.get("bind_C1")
        assert store._store == {}

    def test_development_still_falls_back_to_memory_on_redis_error(self, monkeypatch):
        failing_redis = MagicMock()
        failing_redis.setex.side_effect = ConnectionError("redis down")
        failing_redis.get.side_effect = ConnectionError("redis down")
        monkeypatch.setattr(
            "app.utils.session_store._get_redis_client", lambda: failing_redis
        )
        store = session_store_module.SessionStore()

        store.set("bind_C1", {"bind_state": "selecting"})

        assert store.get("bind_C1") == {"bind_state": "selecting"}
