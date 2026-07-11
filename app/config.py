"""
應用程式設定模組
從環境變數讀取所有敏感設定，不在程式碼中硬編碼任何金鑰。
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── LINE Messaging API ──────────────────────────────────────────────────
    LINE_CHANNEL_ACCESS_TOKEN: str = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    LINE_CHANNEL_SECRET: str = os.environ.get("LINE_CHANNEL_SECRET", "")

    # ── Notion ──────────────────────────────────────────────────────────────
    NOTION_API_TOKEN: str = os.environ.get("NOTION_API_TOKEN", "")
    # Notion 資料庫 ID（從 Notion URL 取得）
    NOTION_DB_FAQ: str = os.environ.get("NOTION_DB_FAQ", "")
    NOTION_DB_SCHEDULE: str = os.environ.get("NOTION_DB_SCHEDULE", "")
    NOTION_DB_HOMEWORK: str = os.environ.get("NOTION_DB_HOMEWORK", "")
    NOTION_DB_EXAMS: str = os.environ.get("NOTION_DB_EXAMS", "")
    NOTION_DB_LEAVES: str = os.environ.get("NOTION_DB_LEAVES", "")
    NOTION_DB_LINE_GROUPS: str = os.environ.get("NOTION_DB_LINE_GROUPS", "")
    NOTION_DB_AI_ALERTS: str = os.environ.get("NOTION_DB_AI_ALERTS", "")
    NOTION_DB_STAFF: str = os.environ.get("NOTION_DB_STAFF", "")
    NOTION_DB_CLASSES: str = os.environ.get("NOTION_DB_CLASSES", "")

    # ── Gemini / LLM ────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    LLM_MODEL: str = os.environ.get("LLM_MODEL", "gemini-3.1-flash-lite")

    # ── 風險通知對象 ─────────────────────────────────────────────────────────
    # 主管或維護者的 LINE userId，用於接收高風險提醒
    ADMIN_LINE_USER_ID: str = os.environ.get("ADMIN_LINE_USER_ID", "")

    # ── 補習班基本資訊 ───────────────────────────────────────────────────────
    CRAM_SCHOOL_NAME: str = os.environ.get("CRAM_SCHOOL_NAME", "Moosie 補習班")
    BOT_NAME: str = os.environ.get("BOT_NAME", "AI班主任")

    # ── 其他 ─────────────────────────────────────────────────────────────────
    DEBUG: bool = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    GENERIC_TIMEZONE: str = os.environ.get("GENERIC_TIMEZONE", "Asia/Taipei")
