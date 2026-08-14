"""
Flask Application Factory
建立並設定 Flask 應用程式實例。
"""
import logging
from flask import Flask
from .config import Config
from .routes import linebot_bp
from .utils.event_deduplicator import EventDeduplicator
from .services.webhook_queue import WebhookQueue


def create_app(config_class: type = Config) -> Flask:
    """建立 Flask 應用程式實例（Application Factory Pattern）。"""
    app = Flask(__name__)

    # 載入設定
    app.config.from_object(config_class)

    # Event 去重需要在同一 app process 中共用；production 不允許 Redis
    # 失敗時退回 instance-local memory，避免多實例產生資料重複寫入。
    is_production = app.config.get("APP_ENV", "development").lower() in {
        "production",
        "prod",
    }
    app.extensions["event_deduplicator"] = EventDeduplicator(
        redis_url=app.config.get("REDIS_URL", ""),
        allow_memory_fallback=not is_production,
    )
    # Queue 在真正入列時才連線 Redis；web 與 worker 共用設定但只由 web service 入列。
    app.extensions["webhook_queue"] = WebhookQueue(app.config)

    # 設定 logging
    logging.basicConfig(
        level=logging.DEBUG if app.config.get("DEBUG") else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 註冊 Blueprint
    app.register_blueprint(linebot_bp)

    return app
