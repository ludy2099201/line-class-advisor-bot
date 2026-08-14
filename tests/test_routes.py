"""Webhook 設定安全性、健康端點與背景入列測試。"""
import base64
import hashlib
import hmac
import json
from unittest.mock import MagicMock


def _signature(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _event(event_id="evt-test"):
    return {
        "type": "message",
        "webhookEventId": event_id,
        "replyToken": "reply-token",
        "source": {"type": "user", "userId": "U_test"},
        "message": {"type": "text", "text": "你好"},
    }


def _post_event(app, client, event):
    body = json.dumps({"events": [event]}, ensure_ascii=False).encode("utf-8")
    return client.post(
        "/linebot",
        data=body,
        content_type="application/json",
        headers={"X-Line-Signature": _signature(body, app.config["LINE_CHANNEL_SECRET"])},
    )


def test_liveness_is_available(client):
    assert client.get("/livez").json == {"status": "alive"}


def test_readiness_is_ready_in_development(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json["status"] == "ready"


def test_readiness_rejects_missing_production_config(app, client):
    app.config.update(APP_ENV="production", LINE_CHANNEL_SECRET="", REDIS_URL="")
    response = client.get("/readyz")
    assert response.status_code == 503
    assert "LINE_CHANNEL_SECRET" in response.json["missing_config"]
    assert "REDIS_URL" in response.json["missing_config"]


def test_production_webhook_fails_closed_without_channel_secret(app, client):
    app.config.update(APP_ENV="production", LINE_CHANNEL_SECRET="")
    response = client.post("/linebot", data=b'{"events": []}', content_type="application/json")
    assert response.status_code == 503
    assert response.json["error"] == "Webhook verification is not configured"


def test_invalid_webhook_signature_has_no_queue_side_effect(app, client):
    queue = MagicMock()
    app.extensions["webhook_queue"] = queue
    response = client.post(
        "/linebot",
        data=b'{"events": []}',
        content_type="application/json",
        headers={"X-Line-Signature": "invalid"},
    )
    assert response.status_code == 400
    queue.enqueue_event.assert_not_called()


def test_valid_webhook_signature_enqueues_event(app, client):
    queue = MagicMock()
    app.extensions["webhook_queue"] = queue
    event = _event("evt-valid-signature")
    response = _post_event(app, client, event)
    assert response.status_code == 200
    queue.enqueue_event.assert_called_once_with(event)


def test_duplicate_webhook_event_is_enqueued_once(app, client):
    queue = MagicMock()
    app.extensions["webhook_queue"] = queue
    event = _event("evt-deduplication-test")
    assert _post_event(app, client, event).status_code == 200
    assert _post_event(app, client, event).status_code == 200
    queue.enqueue_event.assert_called_once_with(event)


def test_production_rejects_when_event_deduplication_is_unavailable(app, client):
    app.config["APP_ENV"] = "production"
    deduplicator = MagicMock()
    deduplicator.claim.return_value = None
    app.extensions["event_deduplicator"] = deduplicator
    response = _post_event(app, client, _event("evt-dedup-unavailable"))
    assert response.status_code == 503
    assert response.json["error"] == "Webhook event deduplication is unavailable"


def test_queue_failure_releases_claim_and_returns_503(app, client):
    from app.services.webhook_queue import WebhookQueueUnavailable

    deduplicator = MagicMock()
    deduplicator.claim.return_value = True
    queue = MagicMock()
    queue.enqueue_event.side_effect = WebhookQueueUnavailable("unavailable")
    app.extensions["event_deduplicator"] = deduplicator
    app.extensions["webhook_queue"] = queue
    response = _post_event(app, client, _event("evt-queue-unavailable"))
    assert response.status_code == 503
    assert response.json["error"] == "Webhook background queue is unavailable"
    deduplicator.release.assert_called_once_with("evt-queue-unavailable")
