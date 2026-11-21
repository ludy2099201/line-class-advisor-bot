"""Multi-turn flow ownership, atomic consumption, and persistence retries."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading
from unittest.mock import Mock

import fakeredis
import pytest

from app.handlers.bind_handler import BindHandler
from app.handlers.leave_handler import LeaveHandler, STATE_WAIT_DATE, STATE_WAIT_NAME, STATE_WAIT_REASON
from app.handlers.note_handler import NoteHandler
import app.utils.session_store as session_store


@pytest.fixture(params=["memory", "redis"])
def store(request, monkeypatch):
    monkeypatch.setattr(session_store, "_MEMORY", {})
    monkeypatch.setattr(session_store, "_CLIENTS", {})
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("redis.from_url", Mock(return_value=client))
    return session_store.SessionStore(
        redis_url="redis://flows" if request.param == "redis" else "",
        allow_memory_fallback=request.param == "memory",
    )


@pytest.fixture(params=["leave", "note", "bind"])
def flow(request, store):
    api = Mock()
    notion = Mock()
    ctx = {"source_type": "user", "user_id": "admin", "reply_token": "reply", "clean_text": "病假"}
    if request.param == "leave":
        handler = LeaveHandler({}, api, notion)
        handler.session = store
        store.transition("admin", STATE_WAIT_REASON, student_name="小明", leave_date="05/10")
        return {
            "handler": handler, "api": api, "notion": notion.create_leave_record,
            "run": lambda: handler.handle(ctx), "read": "get_state",
            "saved": lambda: (store.get_state("admin"), store.get_data("admin", "student_name"),
                              store.get_data("admin", "leave_date")),
            "missing": lambda: store.get_state("admin") is None,
        }
    if request.param == "note":
        handler = NoteHandler(store, notion)
        store.set("admin", {"mode": "note_create", "step": "confirm", "teacher": "老師",
                            "data": {"student": "小明", "content": "學習良好"}})
        return {
            "handler": handler, "api": api, "notion": notion.create_note,
            "run": lambda: handler.handle_step("admin", "確認"), "read": "get",
            "saved": lambda: store.get("admin"), "missing": lambda: store.get("admin") is None,
        }
    handler = BindHandler({}, api, notion, store)
    ctx.update(source_type="group", group_id="group", clean_text="確認")
    store.set("bind_group", {"bind_state": "confirming", "bind_owner": "admin",
                             "bind_selected": {"name": "班級"}, "bind_classes": [{"name": "班級"}]})
    return {
        "handler": handler, "api": api, "notion": notion.bind_group_to_class,
        "run": lambda: handler.handle_step(ctx), "read": "get",
        "saved": lambda: store.get("bind_group"), "missing": lambda: store.get("bind_group") is None,
    }


def test_concurrent_and_replayed_final_step_writes_once(flow, store, monkeypatch):
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    read = getattr(store, flow["read"])
    reads = 0

    def synchronized_read(*args, **kwargs):
        nonlocal reads
        value = read(*args, **kwargs)
        with lock:
            reads += 1
            synchronize = reads <= 2
        if synchronize:
            barrier.wait(timeout=5)
        return value

    monkeypatch.setattr(store, flow["read"], synchronized_read)
    flow["notion"].return_value = True
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: flow["run"](), range(2)))
    flow["run"]()
    flow["notion"].assert_called_once()
    assert flow["missing"]()
    if flow["read"] == "get_state" or isinstance(flow["handler"], BindHandler):
        assert flow["api"].reply.call_count == 1


@pytest.mark.parametrize("failure", [False, RuntimeError("Notion unavailable")])
def test_failure_restores_final_step_and_retry_succeeds(flow, failure):
    before = deepcopy(flow["saved"]())
    flow["notion"].side_effect = [failure, True]
    response = flow["run"]()
    assert flow["saved"]() == before
    message = response if isinstance(response, str) else flow["api"].reply.call_args.args[1]
    assert "再次" in message and "重試" in message
    flow["run"]()
    assert flow["notion"].call_count == 2
    assert flow["missing"]()


def test_leave_transitions_use_one_write(store, monkeypatch):
    handler = LeaveHandler({}, Mock(), Mock())
    handler.session = store
    store.transition("user", STATE_WAIT_NAME)
    transition = Mock(wraps=store.transition)
    monkeypatch.setattr(store, "transition", transition)
    monkeypatch.setattr(store, "set_state", Mock(side_effect=AssertionError("split state write")))
    monkeypatch.setattr(store, "update_data", Mock(side_effect=AssertionError("split data write")))
    handler.handle({"source_type": "user", "user_id": "user", "reply_token": "reply", "clean_text": "小明"})
    transition.assert_called_once_with("user", STATE_WAIT_DATE, student_name="小明")
    assert store.get_state("user") == STATE_WAIT_DATE
    assert store.get_data("user", "student_name") == "小明"
    transition.reset_mock()
    handler.handle({"source_type": "user", "user_id": "user", "reply_token": "reply", "clean_text": "05/10"})
    transition.assert_called_once_with("user", STATE_WAIT_REASON, leave_date="05/10")
    assert store.get_data("user", "student_name") == "小明"


def test_bind_ownership_display_cap_and_cancel(store):
    api, notion = Mock(), Mock()
    notion.list_classes.return_value = [{"name": f"班級{i}"} for i in range(25)]
    handler = BindHandler({}, api, notion, store)
    ctx = {"source_type": "group", "group_id": "group", "user_id": "owner", "reply_token": "reply"}
    handler.handle_start(ctx)
    saved = store.get("bind_group")
    assert saved["bind_owner"] == "owner"
    assert len(saved["bind_classes"]) == 20
    assert "班級19" in api.reply.call_args.args[1]
    assert "班級20" not in api.reply.call_args.args[1]
    api.reply.reset_mock()
    for text in ("1", "確認", "取消", "綁定班級"):
        assert handler.handle_step({**ctx, "user_id": "other", "clean_text": text}) is True
    api.reply.assert_not_called()
    notion.bind_group_to_class.assert_not_called()
    assert store.get("bind_group") == saved
    handler.handle_step({**ctx, "clean_text": "21"})
    assert store.get("bind_group")["bind_state"] == "selecting"
    assert "1–20" in api.reply.call_args.args[1]
    handler.handle_step({**ctx, "clean_text": "20"})
    assert store.get("bind_group")["bind_selected"]["name"] == "班級19"
    handler.handle_step({**ctx, "clean_text": "取消"})
    assert store.get("bind_group") is None


@pytest.mark.parametrize("state", [
    {}, [], "bad", {"mode": "note_create", "step": "unknown", "data": {}},
    {"mode": "note_create", "step": [], "data": {}},
    {"mode": "note_create", "step": "student", "data": []},
    {"mode": "note_create", "step": "confirm", "data": {"performance": []}},
])
def test_note_malformed_step_clears_and_restarts(store, state):
    notion = Mock()
    handler = NoteHandler(store, notion)
    store.set("user", state)
    reply = handler.handle_step("user", "確認")
    assert "課後筆記" in reply and "重新開始" in reply
    assert store.get("user") is None
    notion.create_note.assert_not_called()


def test_note_missing_session_is_ignored(store):
    assert NoteHandler(store, Mock()).handle_step("user", "確認") is None


def test_note_missing_service_preserves_confirmation(store):
    handler = NoteHandler(store)
    state = {"mode": "note_create", "step": "confirm", "data": {}}
    store.set("user", state)
    assert "再次" in handler.handle_step("user", "確認")
    assert store.get("user") == state


def test_take_state_only_consumes_expected_state(store):
    store.transition("user", STATE_WAIT_NAME, student_name="小明")
    assert store.take_state("user", expected_state=STATE_WAIT_REASON) is None
    assert store.get_state("user") == STATE_WAIT_NAME
    record = store.take_state("user", expected_state=STATE_WAIT_NAME)
    assert record["state"] == STATE_WAIT_NAME
    assert record["data"] == {"student_name": "小明"}
    assert store.take_state("user") is None
