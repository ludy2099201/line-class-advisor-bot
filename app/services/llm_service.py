"""
LLM Service — OpenAI API 封裝

支援兩種呼叫模式：
- chat()：一般對話，回傳純文字字串
- chat_json()：強制 JSON 輸出（response_format=json_object），用於風險分析等結構化任務
"""
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_RETRY_DELAY = 1.0  # 秒

SYSTEM_PROMPT = """你是「{bot_name}」，{school_name} 的 AI 班主任助理。

【角色定位】
你被放在班級 LINE 群組中，協助老師處理日常溝通，不是取代真人老師。

【語氣與風格】
- 使用繁體中文，語氣溫和、有禮貌、簡潔
- 不長篇說教，回覆以 1–3 句為原則
- 適時使用表情符號讓訊息更親切，但不過度

【嚴格規則（不可違反）】
1. 不在群組公開任何學生個資（成績、繳費狀態、請假原因）
2. 不假裝自己是真人老師
3. 不做醫療、法律、心理診斷
4. 不處理金流或收費相關操作
5. 遇到超出能力範圍的問題，引導聯繫真人老師

【回覆策略】
- FAQ / 一般問題：直接從資料庫回答
- 請假申請：引導私訊，不在群組收集個資
- 作業 / 課表：查詢 Notion 後簡潔回覆
- 情緒宣洩：溫和回應，必要時通知老師
- 客訴 / 風險訊號：私下通知老師，群組中給予安撫"""


class LlmService:
    """OpenAI API 服務封裝，支援一般對話與結構化 JSON 輸出。"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._client = None  # 延遲初始化

    def _get_client(self):
        """延遲初始化 OpenAI client，避免啟動時因缺少 API key 而崩潰。"""
        if self._client is not None:
            return self._client
        api_key = self.config.get("OPENAI_API_KEY", "")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set; LLM calls will be skipped.")
            return None
        try:
            from openai import OpenAI  # pylint: disable=import-outside-toplevel
            self._client = OpenAI(api_key=api_key)
            return self._client
        except ImportError:
            logger.error("openai package not installed.")
            return None

    def _build_system_prompt(self) -> str:
        """根據設定動態建立 system prompt。"""
        return SYSTEM_PROMPT.format(
            bot_name=self.config.get("BOT_NAME", "AI班主任"),
            school_name=self.config.get("CRAM_SCHOOL_NAME", "補習班"),
        )

    def chat(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 500,
        temperature: float = 0.3,
    ) -> str:
        """
        一般對話呼叫，回傳純文字字串。
        失敗時回傳空字串，不拋出例外。
        """
        client = self._get_client()
        if not client:
            return ""

        model = self.config.get("LLM_MODEL", "gpt-4.1-mini")
        messages = [
            {"role": "system", "content": system_prompt or self._build_system_prompt()},
            {"role": "user", "content": user_message},
        ]

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                content = response.choices[0].message.content or ""
                logger.debug(
                    "LLM chat OK | model=%s | tokens=%d",
                    model,
                    response.usage.total_tokens if response.usage else 0,
                )
                return content.strip()
            except Exception as exc:  # pylint: disable=broad-except
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "LLM chat attempt %d failed: %s, retrying...", attempt + 1, exc
                    )
                    time.sleep(_RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(
                        "LLM chat failed after %d attempts: %s", _MAX_RETRIES + 1, exc
                    )
        return ""

    def chat_json(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 600,
        temperature: float = 0.1,
    ) -> Optional[Dict[str, Any]]:
        """
        強制 JSON 輸出模式（response_format=json_object）。
        適用於風險分析等需要結構化回應的場景。
        回傳解析後的 dict；失敗時回傳 None。
        """
        import json  # pylint: disable=import-outside-toplevel

        client = self._get_client()
        if not client:
            return None

        model = self.config.get("LLM_MODEL", "gpt-4.1-mini")
        messages = [
            {"role": "system", "content": system_prompt or self._build_system_prompt()},
            {"role": "user", "content": user_message},
        ]

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content or "{}"
                result = json.loads(raw)
                logger.debug(
                    "LLM chat_json OK | model=%s | keys=%s", model, list(result.keys())
                )
                return result
            except Exception as exc:  # pylint: disable=broad-except
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "LLM chat_json attempt %d failed: %s, retrying...", attempt + 1, exc
                    )
                    time.sleep(_RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(
                        "LLM chat_json failed after %d attempts: %s", _MAX_RETRIES + 1, exc
                    )
        return None
