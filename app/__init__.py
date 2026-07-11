"""
Flask Application Factory
建立並設定 Flask 應用程式實例。
"""
import logging
from flask import Flask
from .config import Config
from .routes import linebot_bp


def create_app(config_class: type = Config) -> Flask:
    """建立 Flask 應用程式實例（Application Factory Pattern）。"""
    app = Flask(__name__)

    # 載入設定
    app.config.from_object(config_class)

    # 設定 logging
    logging.basicConfig(
        level=logging.DEBUG if app.config.get("DEBUG") else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 註冊 Blueprint
    app.register_blueprint(linebot_bp)

    return app
