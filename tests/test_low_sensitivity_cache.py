from unittest.mock import MagicMock

from app.utils.low_sensitivity_cache import LowSensitivityCache


def test_memory_cache_reuses_low_sensitivity_value(monkeypatch):
    cache = LowSensitivityCache(redis_url="", allow_memory_fallback=True)
    loader = MagicMock(return_value=[{"question": "Q", "answer": "A"}])
    assert cache.get_or_load("test:faq", 60, loader) == [{"question": "Q", "answer": "A"}]
    assert cache.get_or_load("test:faq", 60, loader) == [{"question": "Q", "answer": "A"}]
    loader.assert_called_once()


def test_cache_does_not_require_redis_in_development():
    cache = LowSensitivityCache(redis_url="", allow_memory_fallback=True)
    assert cache.get_or_load("test:classes", 60, lambda: [{"name": "一班"}]) == [{"name": "一班"}]
