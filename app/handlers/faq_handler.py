"""
[1] faq-reply — FAQ 自動回覆 Handler
從 Notion FAQ 資料庫查詢關鍵字，找不到時轉真人處理。
"""
import logging
from typing import Any, Dict

from ..services.line_api import LineApiService
from ..services.notion_service import NotionService
from ..services.llm_service import LlmService

logger = logging.getLogger(__name__)


class FaqHandler:
    """處理家長與學生的常見問題查詢。"""

    def __init__(
        self,
        config: Dict[str, Any],
        line_api: LineApiService,
        notion: NotionService,
    ):
        self.config = config
        self.line_api = line_api
        self.notion = notion
        self.llm = LlmService(config)

    def handle(self, ctx: Dict[str, Any]) -> None:
        """嘗試從 Notion FAQ 資料庫回覆，找不到則轉真人。"""
        clean_text = ctx.get("clean_text", "")
        reply_token = ctx["reply_token"]

        # 1. 從 Notion 查詢 FAQ
        faq_items = self.notion.query_faq()

        # 2. 關鍵字比對
        matched_answer = self._match_faq(clean_text, faq_items)

        if matched_answer:
            logger.info("FAQ matched for query: %s", clean_text[:30])
            self.line_api.reply(reply_token, matched_answer)
        else:
            # 3. 嘗試用 LLM 從 FAQ 清單中找最接近的答案
            llm_answer = self._llm_faq_lookup(clean_text, faq_items)
            if llm_answer:
                logger.info("LLM FAQ answer generated for: %s", clean_text[:30])
                self.line_api.reply(reply_token, llm_answer)
            else:
                # 4. 找不到答案，轉真人
                logger.info("FAQ not found, escalating to human: %s", clean_text[:30])
                self.line_api.reply(
                    reply_token,
                    "感謝您的詢問！這個問題我先幫您通知行政老師，"
                    "稍後會有專人與您確認。🙏",
                )

    def _match_faq(
        self, query: str, faq_items: list
    ) -> str:
        """簡單關鍵字比對，回傳第一個命中的答案。"""
        query_lower = query.lower()
        for item in faq_items:
            keywords = item.get("keywords", [])
            question = item.get("question", "").lower()
            # 比對問題本身或關鍵字標籤
            if question in query_lower or any(kw.lower() in query_lower for kw in keywords):
                return item.get("answer", "")
        return ""

    def _llm_faq_lookup(self, query: str, faq_items: list) -> str:
        """使用 LLM 從 FAQ 清單中找最接近的答案（避免幻覺）。"""
        if not faq_items:
            return ""

        faq_text = "\n".join(
            f"Q: {item.get('question', '')}\nA: {item.get('answer', '')}"
            for item in faq_items[:30]  # 最多取 30 筆避免 token 過多
        )

        prompt = f"""以下是補習班 FAQ 清單：

{faq_text}

使用者問題：「{query}」

請從上方 FAQ 中找出最相關的答案，用繁體中文簡短回覆（1–3 句）。
如果 FAQ 中完全沒有相關資訊，請只回覆「NOT_FOUND」，不要自行編造答案。"""

        response = self.llm.chat(prompt)
        if response and "NOT_FOUND" not in response:
            return response
        return ""
