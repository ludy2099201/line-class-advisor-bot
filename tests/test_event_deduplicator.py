"""Pending claims recover abandoned ingress work; confirmed claims last a day."""
import time
from unittest.mock import Mock

import fakeredis
import pytest
from redis.exceptions import ConnectionError

import app.utils.event_deduplicator as module


@pytest.fixture
def redis_deduplicator(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("redis.from_url", Mock(return_value=client))
    return module.EventDeduplicator(
        redis_url="redis://dedup", allow_memory_fallback=False, pending_ttl_seconds=120,
    ), client


def test_pending_then_promoted_ttl(redis_deduplicator):
    dedup, client = redis_deduplicator
    assert dedup.claim("event") is True
    assert 119 <= client.ttl(dedup._key("event")) <= 120
    assert dedup.confirm("event") is True
    assert 86399 <= client.ttl(dedup._key("event")) <= 86400
    assert dedup.claim("event") is False


def test_crash_before_enqueue_claim_expires(redis_deduplicator, monkeypatch):
    dedup, client = redis_deduplicator
    clock = [time.time()]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    assert dedup.claim("abandoned") is True
    clock[0] += 119
    assert dedup.claim("abandoned") is False
    clock[0] += 2
    assert not client.exists(dedup._key("abandoned"))
    assert dedup.claim("abandoned") is True


def test_confirm_failure_keeps_pending_ttl(redis_deduplicator, monkeypatch, caplog):
    dedup, client = redis_deduplicator
    dedup.claim("event")
    monkeypatch.setattr(client, "expire", Mock(side_effect=ConnectionError("offline")))
    assert dedup.confirm("event") is False
    assert "Unable to confirm" in caplog.text
    assert 119 <= client.ttl(dedup._key("event")) <= 120


def test_confirm_missing_claim_does_not_recreate_it(redis_deduplicator):
    dedup, client = redis_deduplicator
    assert dedup.confirm("missing") is False
    assert not client.exists(dedup._key("missing"))


def test_release_pending_claim(redis_deduplicator):
    dedup, _ = redis_deduplicator
    assert dedup.claim("event") is True
    dedup.release("event")
    assert dedup.claim("event") is True


def test_memory_pending_and_confirmed_expiry(monkeypatch):
    monkeypatch.setattr(module, "_MEMORY_EVENTS", {})
    clock = [time.time()]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    dedup = module.EventDeduplicator(pending_ttl_seconds=10)
    assert dedup.claim("abandoned") is True
    clock[0] += 11
    assert dedup.claim("abandoned") is True
    assert dedup.confirm("abandoned") is True
    clock[0] += 11
    assert dedup.claim("abandoned") is False
    clock[0] += 86400
    assert dedup.claim("abandoned") is True


def test_custom_pending_ttl(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("redis.from_url", Mock(return_value=client))
    dedup = module.EventDeduplicator(redis_url="redis://dedup", pending_ttl_seconds=17)
    dedup.claim("event")
    assert 16 <= client.ttl(dedup._key("event")) <= 17
