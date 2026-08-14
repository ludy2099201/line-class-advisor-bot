"""
LINE Webhook 路由。

接收 LINE 平台的 POST 請求，驗證簽章後交由 Router 處理；在正式環境中，
關鍵設定缺失時採 fail-closed 政策，避免未驗證事件或不完整服務進入營運。
"""
import base64
import hashlib
import hmac
import json
import logging
from typing import List

from flask import Blueprint, abort, current_app, jsonify, request

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


def _is_production() -> bool:
    """判定目前是否應啟用 production 安全政策。"""
    return current_app.config.get("APP_ENV", "development").lower() in {
        "production",
        "prod",
    }


def _missing_production_config() -> List[str]:
    """列出正式環境不可缺少的設定，不揭露其值。"""
    required = current_app.config.get("REQUIRED_PRODUCTION_CONFIG", ())
    return [key for key in required if not current_app.config.get(key)]


@linebot_bp.route("/linebot", methods=["POST"])
def linebot_webhook():
    """LINE Webhook 入口，所有訊息事件由此進入。"""
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data()

    channel_secret = current_app.config.get("LINE_CHANNEL_SECRET", "")
    if not channel_secret:
        if _is_production():
            logger.critical(
                "Rejecting webhook because LINE_CHANNEL_SECRET is missing in production"
            )
            abort(503, description="Webhook verification is not configured")
        logger.warning(
            "LINE_CHANNEL_SECRET is not set; skipping signature verification outside production"
        )
    elif not _verify_signature(body, signature, channel_secret):
        logger.warning("Invalid LINE signature received from IP: %s", request.remote_addr)
        abort(400, description="Invalid signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error("Failed to parse LINE webhook payload: %s", exc)
        abort(400, description="Invalid JSON payload")

    router = LineRouter(current_app.config)
    deduplicator = current_app.extensions["event_deduplicator"]
    events = payload.get("events", [])

    for event in events:
        event_type = event.get("type", "unknown")
        event_id = event.get("webhookEventId", "")
        if not event_id:
            logger.warning(
                "LINE event has no webhookEventId; processing without deduplication | type=%s",
                event_type,
            )
        else:
            claim_result = deduplicator.claim(event_id)
            if claim_result is None:
                logger.error(
                    "Rejecting webhook because event deduplication is unavailable | event_id=%s type=%s",
                    event_id,
                    event_type,
                )
                abort(503, description="Webhook event deduplication is unavailable")
            if not claim_result:
                logger.info(
                    "Duplicate LINE webhook event ignored | event_id=%s type=%s",
                    event_id,
                    event_type,
                )
                continue

        logger.info("Processing LINE webhook event | event_id=%s type=%s", event_id, event_type)
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


@linebot_bp.route("/livez", methods=["GET"])
def liveness_check():
    """存活檢查：只確認 Flask process 可回應，不驗證外部依賴。"""
    return jsonify({"status": "alive"}), 200


@linebot_bp.route("/readyz", methods=["GET"])
def readiness_check():
    """就緒檢查：正式環境必須具備所有安全關鍵設定才能接收流量。"""
    missing = _missing_production_config()
    is_production = _is_production()
    ready = not is_production or not missing
    response = {
        "status": "ready" if ready else "not_ready",
        "environment": current_app.config.get("APP_ENV", "development"),
        "missing_config": missing if is_production else [],
    }
    return jsonify(response), 200 if ready else 503


@linebot_bp.route("/health", methods=["GET"])
def health_check():
    """
    相容性健康檢查，供 Railway / 監控服務使用。

    為不影響既有 Railway 探針，維持 200；編排系統若需判斷是否可接流量，
    應改用 /readyz。
    """
    config = current_app.config
    required_keys = config.get("REQUIRED_PRODUCTION_CONFIG", ())
    missing = [key for key in required_keys if not config.get(key)]
    is_production = _is_production()

    response = {
        "status": "degraded" if is_production and missing else "ok",
        "bot": config.get("BOT_NAME", "AI班主任"),
        "school": config.get("CRAM_SCHOOL_NAME", ""),
        "environment": config.get("APP_ENV", "development"),
        "missing_config": missing if is_production else [],
        "readiness_endpoint": "/readyz",
    }
    return jsonify(response), 200


@linebot_bp.errorhandler(400)
def bad_request(exc):
    """統一的 400 錯誤回應格式。"""
    return jsonify({"error": str(exc.description)}), 400


@linebot_bp.errorhandler(503)
def service_unavailable(exc):
    """統一的 503 錯誤回應格式，不暴露任何設定值。"""
    return jsonify({"error": str(exc.description)}), 503
