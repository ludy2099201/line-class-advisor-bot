"""Pytest 共用 fixture 與隔離測試設定。"""
import pytest

from app import create_app


class TestConfig:
    """不含真實憑證、可明確控制的 Flask 測試設定。"""

    TESTING = True
    APP_ENV = "development"
    DEBUG = False
    GENERIC_TIMEZONE = "Asia/Taipei"
    LINE_CHANNEL_ACCESS_TOKEN = "test_access_token"
    LINE_CHANNEL_SECRET = "test_channel_secret"
    NOTION_API_TOKEN = "test_notion_token"
    GEMINI_API_KEY = "test_gemini_key"
    ADMIN_LINE_USER_ID = "U_test_admin"
    REDIS_URL = "redis://test.invalid:6379/0"
    BOT_NAME = "測試班主任"
    CRAM_SCHOOL_NAME = "測試補習班"
    REQUIRED_PRODUCTION_CONFIG = (
        "LINE_CHANNEL_ACCESS_TOKEN",
        "LINE_CHANNEL_SECRET",
        "NOTION_API_TOKEN",
        "GEMINI_API_KEY",
        "ADMIN_LINE_USER_ID",
        "REDIS_URL",
    )


@pytest.fixture
def app():
    """建立不連接真實外部服務的 Flask app。"""
    app = create_app(TestConfig)
    yield app


@pytest.fixture
def client(app):
    """提供 Flask 測試客戶端。"""
    return app.test_client()
