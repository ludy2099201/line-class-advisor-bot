"""
LINE Webhook 路由
接收 LINE 平台的 POST 請求，驗證簽章後交由 Router 處理。
"""
import hashlib
import hmac
import base64
import json
import logging

from flask import Blueprint, request, abort, current_app, jsonify

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

    channel_secret = current_app.config.get("LINE_CHANNEL_SECRET", "")
    if channel_secret and not _verify_signature(body, signature, channel_secret):
        logger.warning("Invalid LINE signature received from IP: %s", request.remote_addr)
        abort(400, description="Invalid signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error("Failed to parse LINE webhook payload: %s", exc)
        abort(400, description="Invalid JSON payload")

    router = LineRouter(current_app.config)
    events = payload.get("events", [])

    for event in events:
        event_type = event.get("type", "unknown")
        try:
            router.handle(event)
        except ValueError as exc:
            logger.warning("Value error handling event type=%s: %s", event_type, exc)
        except KeyError as exc:
            logger.warning("Missing key in event type=%s: %s", event_type, exc)
        except Exception as exc:  # pylint: disable=broad-except
            # 捕捉未預期例外，記錄完整 stack trace 但不中斷其他事件處理
            logger.exception(
                "Unexpected error handling LINE event type=%s: %s", event_type, exc
            )

    return "OK", 200


@linebot_bp.route("/health", methods=["GET"])
def health_check():
    """
    健康檢查端點，供 Railway / 監控服務使用。
    回傳 JSON 格式的服務狀態，包含版本與設定完整性資訊。
    """
    config = current_app.config
    # 檢查關鍵設定是否已填入
    required_keys = [
        "LINE_CHANNEL_ACCESS_TOKEN",
        "LINE_CHANNEL_SECRET",
        "NOTION_API_TOKEN",
        "OPENAI_API_KEY",
    ]
    missing = [k for k in required_keys if not config.get(k)]

    status = "degraded" if missing else "ok"
    response = {
        "status": status,
        "bot": config.get("BOT_NAME", "AI班主任"),
        "school": config.get("CRAM_SCHOOL_NAME", ""),
        "missing_config": missing,
    }
    http_status = 200 if status == "ok" else 503
    return jsonify(response), http_status


@linebot_bp.errorhandler(400)
def bad_request(exc):
    """統一的 400 錯誤回應格式。"""
    return jsonify({"error": str(exc.description)}), 400
