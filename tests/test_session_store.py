"""
SessionStore 單元測試
測試多輪對話狀態管理邏輯。
"""
import time
import pytest
from app.utils.session_store import SessionStore, SESSION_TTL


@pytest.fixture
def store():
    return SessionStore()


class TestSessionStore:
    def test_initial_state_is_none(self, store):
        assert store.get_state("user_1") is None

    def test_set_and_get_state(self, store):
        store.set_state("user_1", "leave_wait_name", {})
        assert store.get_state("user_1") == "leave_wait_name"

    def test_update_data(self, store):
        store.set_state("user_1", "leave_wait_date", {"student_name": "王小明"})
        store.update_data("user_1", {"leave_date": "05/10"})
        data = store.get_data("user_1")
        assert data["student_name"] == "王小明"
        assert data["leave_date"] == "05/10"

    def test_clear_session(self, store):
        store.set_state("user_1", "some_state")
        store.clear("user_1")
        assert store.get_state("user_1") is None

    def test_expired_session_returns_none(self, store):
        store.set_state("user_1", "leave_wait_name")
        # 手動設定過期時間
        store._store["user_1"]["updated_at"] = time.time() - SESSION_TTL - 1
        assert store.get_state("user_1") is None

    def test_cleanup_expired(self, store):
        store.set_state("user_1", "state_a")
        store.set_state("user_2", "state_b")
        # 讓 user_1 過期
        store._store["user_1"]["updated_at"] = time.time() - SESSION_TTL - 1
        count = store.cleanup_expired()
        assert count == 1
        assert store.get_state("user_1") is None
        assert store.get_state("user_2") == "state_b"
