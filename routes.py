"""
LINE Webhook 路由
接收 LINE 平台的 POST 請求，驗證簽章後交由 Router 處理。
"""
import hashlib
import hmac
import base64
import json
import logging

from flask import Blueprint, request, abort, current_app

from .handlers.router import LineRouter

logger = logging.getLogger(__name__)
linebot_bp = Blueprint("linebot", __name__)


def _verify_signature(body: bytes, signature: str, channel_secret: str) -> bool:
    """驗證 LINE Webhook 簽章（HMAC-SHA256）。"""
    hash_value = hmac.new(
        channel_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(hash_value).decode("utf-8")
    return hmac.compare_digest(expected, signature)


@linebot_bp.route("/linebot", methods=["POST"])
def linebot_webhook():
    """LINE Webhook 入口，所有訊息事件由此進入。"""
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data()

    channel_secret = current_app.config["LINE_CHANNEL_SECRET"]
    if channel_secret and not _verify_signature(body, signature, channel_secret):
        logger.warning("Invalid LINE signature received")
        abort(400, "Invalid signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.error("Failed to parse LINE webhook payload")
        abort(400, "Invalid JSON")

    router = LineRouter(current_app.config)
    for event in payload.get("events", []):
        try:
            router.handle(event)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Error handling LINE event: %s", exc)

    return "OK", 200


@linebot_bp.route("/health", methods=["GET"])
def health_check():
    """健康檢查端點，供 Railway / 監控服務使用。"""
    return {"status": "ok", "bot": current_app.config.get("BOT_NAME", "AI班主任")}, 200
