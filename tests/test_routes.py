"""Webhook 設定安全性與健康端點測試。"""
import base64
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch


def _signature(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def test_liveness_is_available(client):
    response = client.get("/livez")

    assert response.status_code == 200
    assert response.json == {"status": "alive"}


def test_readiness_is_ready_in_development(client):
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json["status"] == "ready"
    assert response.json["missing_config"] == []


def test_readiness_rejects_missing_production_config(app, client):
    app.config.update(
        APP_ENV="production",
        LINE_CHANNEL_SECRET="",
        REDIS_URL="",
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json["status"] == "not_ready"
    assert "LINE_CHANNEL_SECRET" in response.json["missing_config"]
    assert "REDIS_URL" in response.json["missing_config"]


def test_production_webhook_fails_closed_without_channel_secret(app, client):
    app.config.update(APP_ENV="production", LINE_CHANNEL_SECRET="")
    body = b'{"events": []}'

    with patch("app.routes.LineRouter") as router_cls:
        response = client.post("/linebot", data=body, content_type="application/json")

    assert response.status_code == 503
    assert response.json["error"] == "Webhook verification is not configured"
    router_cls.assert_not_called()


def test_invalid_webhook_signature_has_no_side_effect(client):
    body = b'{"events": []}'

    with patch("app.routes.LineRouter") as router_cls:
        response = client.post(
            "/linebot",
            data=body,
            content_type="application/json",
            headers={"X-Line-Signature": "invalid"},
        )

    assert response.status_code == 400
    assert response.json["error"] == "Invalid signature"
    router_cls.assert_not_called()


def test_valid_webhook_signature_dispatches_event(app, client):
    payload = {
        "events": [
            {
                "type": "message",
                "webhookEventId": "evt-valid-signature",
                "replyToken": "reply-token",
                "source": {"type": "user", "userId": "U_test"},
                "message": {"type": "text", "text": "你好"},
            }
        ]
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    signature = _signature(body, app.config["LINE_CHANNEL_SECRET"])

    with patch("app.routes.LineRouter") as router_cls:
        router = router_cls.return_value
        response = client.post(
            "/linebot",
            data=body,
            content_type="application/json",
            headers={"X-Line-Signature": signature},
        )

    assert response.status_code == 200
    router_cls.assert_called_once_with(app.config)
    router.handle.assert_called_once_with(payload["events"][0])


def test_duplicate_webhook_event_is_processed_once(app, client):
    payload = {
        "events": [
            {
                "type": "message",
                "webhookEventId": "evt-deduplication-test",
                "replyToken": "reply-token",
                "source": {"type": "user", "userId": "U_test"},
                "message": {"type": "text", "text": "測試去重"},
            }
        ]
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    signature = _signature(body, app.config["LINE_CHANNEL_SECRET"])

    with patch("app.routes.LineRouter") as router_cls:
        first = client.post(
            "/linebot",
            data=body,
            content_type="application/json",
            headers={"X-Line-Signature": signature},
        )
        second = client.post(
            "/linebot",
            data=body,
            content_type="application/json",
            headers={"X-Line-Signature": signature},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    router_cls.return_value.handle.assert_called_once_with(payload["events"][0])


def test_production_rejects_when_event_deduplication_is_unavailable(app, client):
    app.config["APP_ENV"] = "production"
    deduplicator = MagicMock()
    deduplicator.claim.return_value = None
    app.extensions["event_deduplicator"] = deduplicator
    payload = {
        "events": [
            {
                "type": "message",
                "webhookEventId": "evt-dedup-unavailable",
                "replyToken": "reply-token",
                "source": {"type": "user", "userId": "U_test"},
                "message": {"type": "text", "text": "測試"},
            }
        ]
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    signature = _signature(body, app.config["LINE_CHANNEL_SECRET"])

    with patch("app.routes.LineRouter") as router_cls:
        response = client.post(
            "/linebot",
            data=body,
            content_type="application/json",
            headers={"X-Line-Signature": signature},
        )

    assert response.status_code == 503
    assert response.json["error"] == "Webhook event deduplication is unavailable"
    deduplicator.claim.assert_called_once_with("evt-dedup-unavailable")
    router_cls.return_value.handle.assert_not_called()
