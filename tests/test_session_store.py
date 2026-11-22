"""SessionStore 單元測試。"""
import time
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import fakeredis
import pytest
from redis.exceptions import ConnectionError, ResponseError

from app.handlers import leave_handler, router
import app.utils.session_store as module


@pytest.fixture(autouse=True)
def isolated_store():
    module._MEMORY.clear()
    module._CLIENTS.clear()
    yield
    module._MEMORY.clear()
    module._CLIENTS.clear()


@pytest.fixture
def redis_client(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("redis.from_url", Mock(return_value=client))
    return client


@pytest.fixture
def redis_store(redis_client):
    return module.SessionStore(allow_memory_fallback=False, redis_url="redis://sessions")


@pytest.fixture
def store(monkeypatch):
    """強制使用 In-Memory 後端，避免測試依賴外部 Redis。"""
    monkeypatch.delenv("REDIS_URL", raising=False)
    return module.SessionStore()


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

    def test_expired_session_returns_none(self, store, monkeypatch):
        store.set_state("user_1", "leave_wait_name")
        now = time.time()
        monkeypatch.setattr(module.time, "time", lambda: now + module.SESSION_TTL + 1)

        assert store.get_state("user_1") is None

    def test_cleanup_expired(self, store, monkeypatch):
        now = time.time()
        store.set_state("user_1", "state_a")
        monkeypatch.setattr(module.time, "time", lambda: now + module.SESSION_TTL - 1)
        store.set_state("user_2", "state_b")
        monkeypatch.setattr(module.time, "time", lambda: now + module.SESSION_TTL + 1)

        count = store.cleanup_expired()

        assert count == 1
        assert store.get_state("user_1") is None
        assert store.get_state("user_2") == "state_b"

    def test_raw_key_value_uses_ttl_aware_storage(self, store):
        store.set("bind:group_1", {"state": "selecting"})

        assert store.get("bind:group_1") == {"state": "selecting"}

        store.delete("bind:group_1")
        assert store.get("bind:group_1") is None


@pytest.mark.parametrize("operation", ["connect", "get", "set", "delete", "transition", "take"])
def test_production_outage_raises(monkeypatch, redis_client, operation):
    store = module.SessionStore(allow_memory_fallback=False, redis_url="redis://sessions")
    if operation == "connect":
        monkeypatch.setattr("redis.from_url", Mock(side_effect=ConnectionError("offline")))
        action = lambda: store.get_state("user")
    else:
        method = {"get": "get", "set": "set", "delete": "delete",
                  "transition": "pipeline", "take": "getdel"}[operation]
        monkeypatch.setattr(redis_client, method, Mock(side_effect=ConnectionError("offline")))
        action = {"get": lambda: store.get_state("user"),
                  "set": lambda: store.set("user", {}),
                  "delete": lambda: store.delete("user"),
                  "transition": lambda: store.transition("user", "next"),
                  "take": lambda: store.take("user")}[operation]
    with pytest.raises(module.SessionStoreUnavailable):
        action()
    assert not module._MEMORY


def test_production_without_url_raises():
    with pytest.raises(module.SessionStoreUnavailable):
        module.SessionStore(allow_memory_fallback=False, redis_url="").get_state("user")


def test_outage_fallback_shared_and_copied(monkeypatch):
    monkeypatch.setattr("redis.from_url", Mock(side_effect=ConnectionError("offline")))
    first = module.SessionStore(redis_url="redis://sessions")
    second = module.SessionStore(redis_url="redis://sessions")
    data = {"nested": [1]}
    first.transition("user", "next", value=data)
    data["nested"].append(2)
    assert second.get_state("user") == "next"
    returned = second.get_data("user", "value")
    returned["nested"].append(3)
    assert first.get_data("user", "value") == {"nested": [1]}
    first.set("raw", data)
    data["nested"].append(4)
    returned = second.get("raw")
    returned["nested"].append(5)
    assert first.get("raw") == {"nested": [1, 2]}


def test_reconnect_after_cooldown_and_shared_lazy_client(monkeypatch, redis_client):
    clock = [100]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    factory = Mock(side_effect=[ConnectionError("offline"), redis_client])
    monkeypatch.setattr("redis.from_url", factory)
    first = module.SessionStore(False, "redis://sessions")
    second = module.SessionStore(False, "redis://sessions")
    assert factory.call_count == 0
    with pytest.raises(module.SessionStoreUnavailable):
        first.get_state("user")
    clock[0] += 1
    with pytest.raises(module.SessionStoreUnavailable):
        second.get_state("user")
    assert factory.call_count == 1
    clock[0] += module.REDIS_RETRY_COOLDOWN
    assert second.get_state("user") is None
    first.transition("user", "ready")
    assert second.get_state("user") == "ready"
    assert factory.call_count == 2
    assert factory.call_args.kwargs["socket_connect_timeout"] == 3


@pytest.mark.parametrize("stale", [True, False])
def test_fallback_wins_over_old_or_missing_redis(monkeypatch, redis_client, stale):
    store = module.SessionStore(redis_url="redis://sessions")
    if stale:
        store.set("key", "old")
    original = redis_client.set
    monkeypatch.setattr(redis_client, "set", Mock(side_effect=ConnectionError("offline")))
    store.set("key", "new")
    monkeypatch.setattr(redis_client, "set", original)
    module._CLIENTS.clear()
    assert module.SessionStore(redis_url="redis://sessions").get("key") == "new"
    store.delete("key")
    assert redis_client.get(store._key("key", raw=True)) is None
    assert store.get("key") is None


def test_failed_delete_does_not_resurrect_redis(monkeypatch, redis_client):
    store = module.SessionStore(redis_url="redis://sessions")
    store.set("key", "old")
    original = redis_client.delete
    monkeypatch.setattr(redis_client, "delete", Mock(side_effect=ConnectionError("offline")))
    store.delete("key")
    monkeypatch.setattr(redis_client, "delete", original)
    module._CLIENTS.clear()
    assert module.SessionStore(redis_url="redis://sessions").get("key") is None


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_namespaces_separate_and_deletes_independent(store, redis_store, backend):
    store = store if backend == "memory" else redis_store
    store.set("user", {"mode": "note_create"})
    assert store.get_state("user") is None
    store.transition("user", "leave", name="student")
    store.delete("user")
    assert store.get_state("user") == "leave"
    store.set("user", "raw")
    store.clear("user")
    assert store.get("user") == "raw"


@pytest.mark.parametrize("bad", ["{", "[]", "null", "1", '"text"',
    '{"state": "x", "data": []}',
    '{"state": 1, "data": {}, "expires_at": 9999999999}',
    '{"state": "x", "data": [], "expires_at": 9999999999}',
    '{"state": "__raw__", "data": {}, "expires_at": 9999999999}',
    '{"state": "x", "data": {}, "expires_at": "bad"}'])
def test_corrupt_state_removed(redis_store, redis_client, bad):
    key = redis_store._key("user")
    redis_client.set(key, bad)
    assert redis_store.get_state("user") is None
    assert redis_client.get(key) is None


@pytest.mark.parametrize("bad", ["{", "[]", '{"state":"__raw__"}',
    '{"state":"x","data":{},"expires_at":9999999999}'])
def test_corrupt_raw_removed(redis_store, redis_client, bad):
    key = redis_store._key("key", raw=True)
    redis_client.set(key, bad)
    assert redis_store.get("key") is None
    assert redis_client.get(key) is None


@pytest.mark.parametrize("value", ["0", "-1", "bad", "1.5"])
def test_invalid_ttl_warns_and_defaults(monkeypatch, caplog, value):
    monkeypatch.setenv("SESSION_TTL_SECONDS", value)
    assert module._session_ttl_seconds() == 1800
    assert "Invalid SESSION_TTL_SECONDS" in caplog.text


@pytest.mark.parametrize("value,expected", [("", 1800), (" 60 ", 60)])
def test_valid_ttl(monkeypatch, value, expected):
    monkeypatch.setenv("SESSION_TTL_SECONDS", value)
    assert module._session_ttl_seconds() == expected


def test_transition_single_write_preserves_data(redis_store, redis_client, monkeypatch):
    redis_store.transition("user", "first", old=1)
    pipeline = redis_client.pipeline
    writes = []

    def tracked_pipeline(*args, **kwargs):
        pipe = pipeline(*args, **kwargs)
        original = pipe.set

        def set_value(*args, **kwargs):
            writes.append(args)
            return original(*args, **kwargs)

        monkeypatch.setattr(pipe, "set", set_value)
        return pipe

    monkeypatch.setattr(redis_client, "pipeline", tracked_pipeline)
    redis_store.transition("user", "second", new=2)
    assert len(writes) == 1
    record = json.loads(writes[0][1])
    assert record["state"] == "second"
    assert record["data"] == {"old": 1, "new": 2}
    assert 0 < redis_client.ttl(redis_store._key("user")) <= module.SESSION_TTL


@pytest.mark.parametrize("backend", ["memory", "redis", "old_server", "old_client"])
def test_take_once_concurrently(store, redis_store, redis_client, monkeypatch, backend):
    store = store if backend == "memory" else redis_store
    if backend in {"old_server", "old_client"}:
        error = ResponseError("unknown command 'GETDEL'") if backend == "old_server" else AttributeError()
        monkeypatch.setattr(redis_client, "getdel", Mock(side_effect=error))
    store.set("key", {"value": 1})
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.take("key"), range(8)))
    assert results.count({"value": 1}) == 1
    assert results.count(None) == 7
    assert store.get("key") is None


def test_take_corrupt_value_removes_it(redis_store, redis_client):
    key = redis_store._key("key", raw=True)
    redis_client.set(key, "not json")
    assert redis_store.take("key") is None
    assert not redis_client.exists(key)


def test_reads_do_not_refresh_ttl(redis_store, redis_client, monkeypatch):
    redis_store.transition("user", "ready")
    write = Mock(wraps=redis_client.set)
    monkeypatch.setattr(redis_client, "set", write)
    assert redis_store.get_state("user") == "ready"
    write.assert_not_called()


@pytest.mark.parametrize("environment,allowed", [
    ("production", False), ("prod", False), ("PRODUCTION", False), ("development", True),
])
def test_handler_constructor_policy(monkeypatch, environment, allowed):
    config = {"APP_ENV": environment, "REDIS_URL": "redis://sessions"}
    constructor = Mock()
    monkeypatch.setattr(leave_handler, "SessionStore", constructor)
    leave_handler.LeaveHandler(config, Mock(), Mock())
    constructor.assert_called_once_with(allow_memory_fallback=allowed, redis_url="redis://sessions")
    constructor.reset_mock()
    monkeypatch.setattr(router, "SessionStore", constructor)
    monkeypatch.setattr(router, "LineApiService", Mock())
    monkeypatch.setattr(router, "NotionService", Mock())
    for name in ("FaqHandler", "ScheduleHandler", "HomeworkHandler", "LeaveHandler", "RiskHandler"):
        monkeypatch.setattr(router, name, Mock())
    router.LineRouter(config)
    constructor.assert_called_once_with(allow_memory_fallback=allowed, redis_url="redis://sessions")


def test_reconnect_after_command_failure(monkeypatch, redis_client):
    clock = [100]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    broken = Mock()
    broken.get.side_effect = ConnectionError("offline")
    factory = Mock(side_effect=[broken, redis_client])
    monkeypatch.setattr("redis.from_url", factory)
    store = module.SessionStore(False, "redis://sessions")
    with pytest.raises(module.SessionStoreUnavailable):
        store.get_state("user")
    clock[0] += module.REDIS_RETRY_COOLDOWN + 1
    assert store.get_state("user") is None
    assert factory.call_count == 2


def test_take_fallback_only_once(monkeypatch):
    monkeypatch.setattr("redis.from_url", Mock(side_effect=ConnectionError("offline")))
    first = module.SessionStore(redis_url="redis://sessions")
    second = module.SessionStore(redis_url="redis://sessions")
    first.set("raw", {"value": 1})
    assert second.take("raw") == {"value": 1}
    assert first.take("raw") is None


def test_namespace_prefixes_cannot_collide(redis_store):
    redis_store.set("user", {"mode": "note_create"})
    redis_store.transition("raw:user", "leave")
    assert redis_store.get("user") == {"mode": "note_create"}
    assert redis_store.get_state("raw:user") == "leave"


def test_corrupt_cleanup_keeps_concurrent_replacement(redis_store, redis_client):
    key = redis_store._key("U1")
    redis_client.set(key, "not json")
    fresh = json.dumps({"state": "WAIT_DATE", "data": {}, "expires_at": time.time() + 60})
    real_get = redis_client.get

    def get_then_replace(name):
        value = real_get(name)
        redis_client.set(name, fresh)
        return value

    redis_client.get = get_then_replace
    assert redis_store.get_state("U1") is None
    redis_client.get = real_get
    assert real_get(key) == fresh
