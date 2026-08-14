"""
應用程式設定模組。

所有敏感設定皆由環境變數提供；正式環境透過 routes 的 readiness
檢查與 webhook fail-closed 政策，拒絕在關鍵設定缺漏時處理事件。
"""
import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """由環境變數建立的應用程式設定。"""

    # ── 執行環境 ──────────────────────────────────────────────────────────────
    APP_ENV: str = os.environ.get("APP_ENV", "development").strip().lower()
    DEBUG: bool = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    GENERIC_TIMEZONE: str = os.environ.get("GENERIC_TIMEZONE", "Asia/Taipei")

    # ── LINE Messaging API ──────────────────────────────────────────────────
    LINE_CHANNEL_ACCESS_TOKEN: str = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    LINE_CHANNEL_SECRET: str = os.environ.get("LINE_CHANNEL_SECRET", "")

    # ── Notion ──────────────────────────────────────────────────────────────
    NOTION_API_TOKEN: str = os.environ.get("NOTION_API_TOKEN", "")
    NOTION_DB_FAQ: str = os.environ.get("NOTION_DB_FAQ", "")
    NOTION_DB_SCHEDULE: str = os.environ.get("NOTION_DB_SCHEDULE", "")
    NOTION_DB_HOMEWORK: str = os.environ.get("NOTION_DB_HOMEWORK", "")
    NOTION_DB_EXAMS: str = os.environ.get("NOTION_DB_EXAMS", "")
    NOTION_DB_LEAVES: str = os.environ.get("NOTION_DB_LEAVES", "")
    NOTION_DB_LINE_GROUPS: str = os.environ.get("NOTION_DB_LINE_GROUPS", "")
    NOTION_DB_AI_ALERTS: str = os.environ.get("NOTION_DB_AI_ALERTS", "")
    NOTION_DB_STAFF: str = os.environ.get("NOTION_DB_STAFF", "")
    NOTION_DB_CLASSES: str = os.environ.get("NOTION_DB_CLASSES", "")
    NOTION_DB_NOTES: str = os.environ.get("NOTION_DB_NOTES", "")

    # ── Gemini / LLM ────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    LLM_MODEL: str = os.environ.get("LLM_MODEL", "gemini-3.1-flash-lite")

    # ── Redis ───────────────────────────────────────────────────────────────
    REDIS_URL: str = os.environ.get("REDIS_URL", "")

    # ── 角色與風險通知對象 ───────────────────────────────────────────────────
    # ADMIN_LINE_USER_ID 保留為正式環境的最低必要單一管理員；
    # 多管理員與教職員 allowlist 使用逗號分隔的 LINE user ID。
    ADMIN_LINE_USER_ID: str = os.environ.get("ADMIN_LINE_USER_ID", "")
    ADMIN_LINE_USER_IDS: str = os.environ.get("ADMIN_LINE_USER_IDS", "")
    STAFF_LINE_USER_IDS: str = os.environ.get("STAFF_LINE_USER_IDS", "")

    # ── 快取（僅適用於低敏感 FAQ 與班級清單）────────────────────────────────
    FAQ_CACHE_TTL_SECONDS: int = int(os.environ.get("FAQ_CACHE_TTL_SECONDS", "900"))
    CLASS_LIST_CACHE_TTL_SECONDS: int = int(
        os.environ.get("CLASS_LIST_CACHE_TTL_SECONDS", "300")
    )

    # ── 補習班基本資訊 ───────────────────────────────────────────────────────
    CRAM_SCHOOL_NAME: str = os.environ.get("CRAM_SCHOOL_NAME", "Moosie 補習班")
    BOT_NAME: str = os.environ.get("BOT_NAME", "AI班主任")

    # 在 production 中，缺少任一項設定都不得處理 webhook。Redis 亦列入其中，
    # 因多實例部署時以 instance-local fallback 處理敏感 session 會造成狀態分裂。
    REQUIRED_PRODUCTION_CONFIG = (
        "LINE_CHANNEL_ACCESS_TOKEN",
        "LINE_CHANNEL_SECRET",
        "NOTION_API_TOKEN",
        "GEMINI_API_KEY",
        "ADMIN_LINE_USER_ID",
        "REDIS_URL",
    )

    @classmethod
    def is_production(cls) -> bool:
        """判定是否採用 production 安全政策。"""
        return cls.APP_ENV in {"production", "prod"}
