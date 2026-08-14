import os
from importlib import reload


def test_blank_optional_numeric_values_use_safe_defaults(monkeypatch):
    monkeypatch.setenv("FAQ_CACHE_TTL_SECONDS", "")
    monkeypatch.setenv("CLASS_LIST_CACHE_TTL_SECONDS", "")
    monkeypatch.setenv("WEBHOOK_JOB_TIMEOUT_SECONDS", "")
    monkeypatch.setenv("WEBHOOK_JOB_MAX_RETRIES", "")
    import app.config as config_module

    reload(config_module)
    assert config_module.Config.FAQ_CACHE_TTL_SECONDS == 900
    assert config_module.Config.CLASS_LIST_CACHE_TTL_SECONDS == 300
    assert config_module.Config.WEBHOOK_JOB_TIMEOUT_SECONDS == 120
    assert config_module.Config.WEBHOOK_JOB_MAX_RETRIES == 0


def test_invalid_optional_numeric_values_use_safe_defaults(monkeypatch):
    monkeypatch.setenv("FAQ_CACHE_TTL_SECONDS", "not-a-number")
    import app.config as config_module

    reload(config_module)
    assert config_module.Config.FAQ_CACHE_TTL_SECONDS == 900
