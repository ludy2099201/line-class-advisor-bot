"""LINE Messaging API 服務封裝。"""
import logging
import time
import uuid
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_REQUEST_TIMEOUT_SECONDS = 10
LINE_PUSH_MAX_RETRIES = 2
LINE_RETRY_BACKOFF_SECONDS = 0.5


class LineApiService:
    """封裝 LINE reply、push 與 Flex Message 呼叫。"""

    def __init__(self, config: Dict[str, Any]):
        self.access_token = config.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    def reply(self, reply_token: str, text: str) -> bool:
        """使用 replyToken 回覆訊息；reply token 不可安全重試。"""
        if not reply_token or not text:
            logger.warning("reply called with empty token or text")
            return False

        payload = {
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": text[:5000]}],
        }
        try:
            resp = requests.post(
                LINE_REPLY_URL,
                json=payload,
                headers=self._headers,
                timeout=LINE_REQUEST_TIMEOUT_SECONDS,
            )
            request_id = resp.headers.get("x-line-request-id", "")
            if resp.status_code != 200:
                logger.error(
                    "LINE reply failed: status=%s request_id=%s body=%s",
                    resp.status_code,
                    request_id,
                    resp.text[:200],
                )
                return False
            return True
        except requests.RequestException as exc:
            logger.exception("LINE reply request error: %s", exc)
            return False

    def push_message(
        self,
        user_id: str,
        text: str,
        retry_key: Optional[str] = None,
    ) -> bool:
        """
        主動推播訊息給指定使用者。

        Push API 支援 X-Line-Retry-Key。相同 key 的 409 代表 LINE 已接受原請求，
        因此視為成功；僅對網路錯誤或 5xx 做有限次重試，避免重複傳送。
        """
        if not user_id or not text:
            logger.warning("push_message called with empty user_id or text")
            return False

        payload = {
            "to": user_id,
            "messages": [{"type": "text", "text": text[:5000]}],
        }
        retry_key = retry_key or str(uuid.uuid4())
        headers = {**self._headers, "X-Line-Retry-Key": retry_key}

        for attempt in range(LINE_PUSH_MAX_RETRIES + 1):
            try:
                resp = requests.post(
                    LINE_PUSH_URL,
                    json=payload,
                    headers=headers,
                    timeout=LINE_REQUEST_TIMEOUT_SECONDS,
                )
                request_id = resp.headers.get("x-line-request-id", "")
                accepted_request_id = resp.headers.get("x-line-accepted-request-id", "")

                if resp.status_code == 200:
                    logger.info(
                        "LINE push accepted: request_id=%s retry_key=%s",
                        request_id,
                        retry_key,
                    )
                    return True
                if resp.status_code == 409:
                    logger.info(
                        "LINE push already accepted: request_id=%s accepted_request_id=%s retry_key=%s",
                        request_id,
                        accepted_request_id,
                        retry_key,
                    )
                    return True

                if 500 <= resp.status_code < 600 and attempt < LINE_PUSH_MAX_RETRIES:
                    self._sleep_before_retry(attempt, retry_key, resp.status_code)
                    continue

                logger.error(
                    "LINE push failed: status=%s request_id=%s retry_key=%s body=%s",
                    resp.status_code,
                    request_id,
                    retry_key,
                    resp.text[:200],
                )
                return False
            except requests.RequestException as exc:
                if attempt < LINE_PUSH_MAX_RETRIES:
                    self._sleep_before_retry(attempt, retry_key, "network_error")
                    continue
                logger.exception(
                    "LINE push request error after retries: retry_key=%s error=%s",
                    retry_key,
                    exc,
                )
                return False

        return False

    @staticmethod
    def _sleep_before_retry(attempt: int, retry_key: str, reason: Any) -> None:
        """採 bounded exponential backoff，並保留 retry key 以維持 idempotency。"""
        delay = LINE_RETRY_BACKOFF_SECONDS * (2**attempt)
        logger.warning(
            "Retrying LINE push: attempt=%s delay_seconds=%.1f retry_key=%s reason=%s",
            attempt + 1,
            delay,
            retry_key,
            reason,
        )
        time.sleep(delay)

    def reply_flex(self, reply_token: str, alt_text: str, flex_contents: dict) -> bool:
        """回覆 Flex Message；reply token 不可安全重試。"""
        if not reply_token:
            return False

        payload = {
            "replyToken": reply_token,
            "messages": [
                {
                    "type": "flex",
                    "altText": alt_text,
                    "contents": flex_contents,
                }
            ],
        }

        try:
            resp = requests.post(
                LINE_REPLY_URL,
                json=payload,
                headers=self._headers,
                timeout=LINE_REQUEST_TIMEOUT_SECONDS,
            )
            request_id = resp.headers.get("x-line-request-id", "")
            if resp.status_code != 200:
                logger.error(
                    "LINE flex reply failed: status=%s request_id=%s body=%s",
                    resp.status_code,
                    request_id,
                    resp.text[:200],
                )
                return False
            return True
        except requests.RequestException as exc:
            logger.exception("LINE flex reply error: %s", exc)
            return False
