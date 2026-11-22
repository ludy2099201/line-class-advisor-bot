"""TTL-bound Redis sessions with development-only process-memory fallback."""
from copy import deepcopy
import json
import logging
import math
import os
import threading
import time
from typing import Any, Optional

import redis
from redis.exceptions import ResponseError, WatchError

logger = logging.getLogger(__name__)


def _session_ttl_seconds() -> int:
    value = os.environ.get("SESSION_TTL_SECONDS")
    if value is None:
        return 1800
    try:
        ttl = int(value.strip())
        if ttl > 0:
            return ttl
    except ValueError:
        pass
    logger.warning("Invalid SESSION_TTL_SECONDS; using 1800 seconds")
    return 1800


SESSION_TTL = _session_ttl_seconds()
REDIS_RETRY_COOLDOWN = 2
_LOCK = threading.RLock()
_MEMORY = {}
_CLIENTS = {}
_UNCHANGED = object()


class SessionStoreUnavailable(RuntimeError):
    """Persistence is unavailable and memory fallback is forbidden."""


class SessionStore:
    """State and raw values use separate namespaces.

    Development fallback is sticky per key until TTL expiry: memory wins over
    Redis, including deletion tombstones, so stale Redis values cannot reappear
    during that interval. This policy is intentionally process-local.
    """

    def __init__(self, allow_memory_fallback: bool = True, redis_url: Optional[str] = None):
        self.allow_memory_fallback = allow_memory_fallback
        self.redis_url = os.environ.get("REDIS_URL", "") if redis_url is None else redis_url

    def _client(self):
        if not self.redis_url:
            raise SessionStoreUnavailable("REDIS_URL is not configured")
        with _LOCK:
            identity = (os.getpid(), self.redis_url)
            client, retry_at = _CLIENTS.get(identity, (None, 0))
            if time.monotonic() < retry_at:
                raise SessionStoreUnavailable("Redis session reconnect cooldown")
            if client is None:
                client = redis.from_url(
                    self.redis_url, decode_responses=True,
                    socket_connect_timeout=3, socket_timeout=3,
                )
                _CLIENTS[identity] = (client, 0)
            return client

    def _unavailable(self, exc):
        if self.redis_url:
            with _LOCK:
                identity = (os.getpid(), self.redis_url)
                # Do not extend the cooldown on requests arriving during it.
                if _CLIENTS.get(identity, (None, 0))[1] <= time.monotonic():
                    _CLIENTS[identity] = (None, time.monotonic() + REDIS_RETRY_COOLDOWN)
        if not self.allow_memory_fallback:
            raise SessionStoreUnavailable("Redis session operation failed") from exc
        if self.redis_url:
            logger.warning("Redis session operation failed; using process memory: %s", exc)

    @staticmethod
    def _key(key: str, raw: bool = False) -> str:
        return f"session-raw:{key}" if raw else f"session:{key}"

    def _memory_key(self, key):
        return (os.getpid(), self.redis_url, key)

    def _memory_get(self, key):
        identity = self._memory_key(key)
        item = _MEMORY.get(identity)
        if item is not None and item[0] <= time.time():
            del _MEMORY[identity]
            item = None
        return item

    def _memory_save(self, key, record):
        _MEMORY[self._memory_key(key)] = (time.time() + SESSION_TTL, deepcopy(record))

    @staticmethod
    def _decode(value, raw):
        if value is None:
            return None
        try:
            record = json.loads(value)
            if not isinstance(record, dict):
                raise ValueError("record must be a dict")
            expiry = record.get("expires_at")
            if (not isinstance(expiry, (int, float)) or isinstance(expiry, bool)
                    or not math.isfinite(expiry)):
                raise ValueError("invalid expiry")
            if raw:
                if record.get("state") != "__raw__" or "data" not in record:
                    raise ValueError("invalid raw record")
            elif ("state" not in record or not isinstance(record.get("data"), dict)
                  or not (record["state"] is None or isinstance(record["state"], str))
                  or record["state"] == "__raw__"):
                raise ValueError("invalid state record")
            return record if expiry > time.time() else None
        except (ValueError, TypeError, OverflowError, RecursionError):
            logger.warning("Discarding corrupt or wrong-shaped session record")
            return None

    def _read(self, key, raw=False, take=False, expected_state=None):
        with _LOCK:
            if self.allow_memory_fallback:
                item = self._memory_get(key)
                if item is not None:
                    if (expected_state is not None and item[1] is not None
                            and item[1].get("state") != expected_state):
                        return None
                    if take:
                        self._delete(key)
                    return deepcopy(item[1])
            try:
                client = self._client()
                value = self._getdel(client, key, expected_state) if take else client.get(key)
                record = self._decode(value, raw)
                if value is not None and record is None and not take:
                    self._delete_if_unchanged(client, key, value)
                return record
            except Exception as exc:  # pylint: disable=broad-except
                self._unavailable(exc)
                return None

    @staticmethod
    def _delete_if_unchanged(client, key, value):
        """Delete a discarded record only if no other writer replaced it meanwhile."""
        with client.pipeline() as pipe:
            try:
                pipe.watch(key)
                if pipe.get(key) != value:
                    return
                pipe.multi()
                pipe.delete(key)
                pipe.execute()
            except WatchError:
                pass

    @staticmethod
    def _getdel(client, key, expected_state=None):
        if expected_state is None:
            try:
                return client.getdel(key)
            except AttributeError:
                pass
            except ResponseError as exc:
                if "unknown command" not in str(exc).lower():
                    raise
        while True:
            with client.pipeline() as pipe:
                try:
                    pipe.watch(key)
                    value = pipe.get(key)
                    if expected_state is not None:
                        record = SessionStore._decode(value, False)
                        if record is not None and record["state"] != expected_state:
                            return None
                    pipe.multi()
                    pipe.delete(key)
                    pipe.execute()
                    return value
                except WatchError:
                    continue

    def _write(self, key, record):
        with _LOCK:
            if self.allow_memory_fallback and self._memory_get(key) is not None:
                self._memory_save(key, record)
                return
            try:
                self._client().set(key, json.dumps(record, ensure_ascii=False), ex=SESSION_TTL)
            except Exception as exc:  # pylint: disable=broad-except
                self._unavailable(exc)
                self._memory_save(key, record)

    def _delete(self, key):
        with _LOCK:
            _MEMORY.pop(self._memory_key(key), None)
            try:
                self._client().delete(key)
            except Exception as exc:  # pylint: disable=broad-except
                self._unavailable(exc)
                self._memory_save(key, None)

    def get_state(self, user_id: str) -> Optional[str]:
        record = self._read(self._key(user_id))
        return record.get("state") if record else None

    def set_state(self, user_id: str, state: str) -> None:
        self.transition(user_id, state)

    def get_data(self, user_id: str, key: str, default: Any = None) -> Any:
        record = self._read(self._key(user_id))
        return record["data"].get(key, default) if record else default

    def update_data(self, user_id: str, **kwargs) -> None:
        self.transition(user_id, _UNCHANGED, **kwargs)

    def transition(self, user_id: str, state: str, **data) -> None:
        """Atomically merge data and change state with one persisted write."""
        key = self._key(user_id)

        def updated(record):
            record = deepcopy(record) if record else {"state": None, "data": {}}
            if state is not _UNCHANGED:
                record["state"] = state
            record["data"].update(deepcopy(data))
            record["expires_at"] = time.time() + SESSION_TTL
            return record

        with _LOCK:
            if self.allow_memory_fallback:
                item = self._memory_get(key)
                if item is not None:
                    self._memory_save(key, updated(item[1]))
                    return
            record = None
            try:
                client = self._client()
                while True:
                    with client.pipeline() as pipe:
                        try:
                            pipe.watch(key)
                            previous = pipe.get(key)
                            record = self._decode(previous, False)
                            value = updated(record)
                            pipe.multi()
                            if previous is not None and record is None:
                                pipe.delete(key)
                            pipe.set(key, json.dumps(value, ensure_ascii=False), ex=SESSION_TTL)
                            pipe.execute()
                            return
                        except WatchError:
                            continue
            except Exception as exc:  # pylint: disable=broad-except
                self._unavailable(exc)
                self._memory_save(key, updated(record))

    def clear(self, user_id: str) -> None:
        """Delete a state session; use delete() for raw values."""
        self._delete(self._key(user_id))

    def take_state(self, user_id: str, expected_state: Optional[str] = None) -> Optional[dict]:
        """Consume a state session, optionally only when its state still matches."""
        return self._read(self._key(user_id), take=True, expected_state=expected_state)

    def set(self, key: str, value: Any) -> None:
        record = {"state": "__raw__", "data": value, "expires_at": time.time() + SESSION_TTL}
        self._write(self._key(key, raw=True), record)

    def get(self, key: str) -> Optional[Any]:
        record = self._read(self._key(key, raw=True), raw=True)
        return record["data"] if record else None

    def take(self, key: str) -> Optional[Any]:
        """Atomically read and delete a raw value."""
        record = self._read(self._key(key, raw=True), raw=True, take=True)
        return record["data"] if record else None

    def delete(self, key: str) -> None:
        self._delete(self._key(key, raw=True))

    def cleanup_expired(self) -> int:
        with _LOCK:
            expired = [key for key, item in _MEMORY.items() if item[0] <= time.time()]
            for key in expired:
                del _MEMORY[key]
            return len(expired)
