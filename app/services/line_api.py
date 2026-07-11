"""
LINE Messaging API 服務封裝
提供 reply_message 與 push_message 功能。
"""
import logging
from typing import Any, Dict

import requests

logger = logging.getLogger(__name__)

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


class LineApiService:
    """封裝 LINE Messaging API 呼叫。"""

    def __init__(self, config: Dict[str, Any]):
        self.access_token = config.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    def reply(self, reply_token: str, text: str) -> bool:
        """使用 replyToken 回覆訊息（每個 token 只能用一次）。"""
        if not reply_token or not text:
            logger.warning("reply called with empty token or text")
            return False

        payload = {
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": text[:5000]}],  # LINE 單則上限 5000 字
        }

        try:
            resp = requests.post(
                LINE_REPLY_URL,
                json=payload,
                headers=self._headers,
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error(
                    "LINE reply failed: status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            return True
        except requests.RequestException as exc:
            logger.exception("LINE reply request error: %s", exc)
            return False

    def push_message(self, user_id: str, text: str) -> bool:
        """主動推播訊息給指定使用者（需要 push 權限）。"""
        if not user_id or not text:
            logger.warning("push_message called with empty user_id or text")
            return False

        payload = {
            "to": user_id,
            "messages": [{"type": "text", "text": text[:5000]}],
        }

        try:
            resp = requests.post(
                LINE_PUSH_URL,
                json=payload,
                headers=self._headers,
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error(
                    "LINE push failed: status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            return True
        except requests.RequestException as exc:
            logger.exception("LINE push request error: %s", exc)
            return False

    def reply_flex(self, reply_token: str, alt_text: str, flex_contents: dict) -> bool:
        """回覆 Flex Message（結構化訊息，第二階段使用）。"""
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
                timeout=10,
            )
            return resp.status_code == 200
        except requests.RequestException as exc:
            logger.exception("LINE flex reply error: %s", exc)
            return False
