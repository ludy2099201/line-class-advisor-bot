"""
LLM 服務封裝
使用 OpenAI API 進行 FAQ 比對與風險分析。
系統 Prompt 依照附件規格設計，確保 AI 班主任角色一致。
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是「{school_name}」的 LINE 群組 AI 班主任。

你的任務：
1. 協助老師與行政維持班級群組秩序。
2. 回答補習班常見問題。
3. 提醒課表、作業、考試與補課事項。
4. 用溫暖、簡短、清楚的繁體中文回覆。
5. 發現高風險訊息時，保守處理並提醒真人老師。

語氣：
- 台灣繁體中文
- 溫和、有禮貌、有班主任感
- 不油膩、不裝熟、不過度熱情
- 不使用簡體中文
- 不長篇說教
- 群組公開回覆通常 1–3 句即可

嚴格規則：
- 不公開評論單一學生的成績、能力、排名、個性或家庭狀況。
- 不在群組公開揭露電話、地址、學費、繳費、成績、請假原因等個資。
- 不假裝自己是真人老師。
- 不做醫療、法律、心理診斷。
- 不處理金流承諾，不說「已收款」除非系統資料明確確認。
- 不確定時，請說「我先幫您轉請老師／行政確認」。

回覆策略：
- 如果是 FAQ：簡短回答，必要時請洽行政。
- 如果是請假：引導私訊或填表，不在群組收集詳細個資。
- 如果是作業／課表／考試：依資料回覆。
- 如果是學生情緒低落：溫和支持，但不要公開分析。
- 如果是家長客訴：先安撫，並說會請行政或老師協助確認。
- 如果不是明確問你，通常不要回覆。"""


class LlmService:
    """封裝 LLM API 呼叫（OpenAI 相容介面）。"""

    def __init__(self, config: Dict[str, Any]):
        self.api_key = config.get("OPENAI_API_KEY", "")
        self.model = config.get("LLM_MODEL", "gpt-4.1-mini")
        self.school_name = config.get("CRAM_SCHOOL_NAME", "Moosie 補習班")
        self._client = None

    def _get_client(self):
        """延遲初始化 OpenAI client。"""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
            except ImportError:
                logger.error("openai package not installed. Run: pip install openai")
                raise
        return self._client

    def chat(self, user_message: str, system_override: Optional[str] = None) -> str:
        """呼叫 LLM 取得回覆。"""
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not configured, skipping LLM call")
            return ""

        system = system_override or SYSTEM_PROMPT.format(school_name=self.school_name)

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=500,
                temperature=0.3,  # 低 temperature 確保回覆穩定
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("LLM call failed: %s", exc)
            return ""
