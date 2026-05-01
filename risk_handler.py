"""
[5] risk-alert — 風險訊息偵測與通知 Handler
偵測客訴、霸凌、情緒危機、個資外洩等訊號，私下通知老師／行政。
群組中不公開展開討論，保護當事人隱私。
"""
import logging
from typing import Any, Dict

from ..services.line_api import LineApiService
from ..services.notion_service import NotionService
from ..services.llm_service import LlmService

logger = logging.getLogger(__name__)

RISK_ANALYSIS_PROMPT = """你是補習班 AI 班主任的風險分析模組。

請分析以下訊息，判斷是否包含需要真人老師介入的風險訊號。

訊息內容：「{message}」

請以 JSON 格式回覆，欄位說明如下：
- riskLevel: "none" | "low" | "medium" | "high"
- category: "情緒" | "霸凌" | "客訴" | "個資" | "安全" | "其他"
- shouldAlertTeacher: true | false
- publicReplyAllowed: true | false（是否可在群組公開回覆）
- suggestedPrivateAlert: 給老師看的簡短摘要（20字以內）
- suggestedPublicReply: 若允許公開回覆，給群組看的簡短回覆（1–2句）

判斷標準：
- high：情緒危機（不想活、想死）、暴力威脅、跟蹤、緊急安全事件
- medium：客訴、霸凌訊號、個資外洩風險
- low：輕微不滿、一般情緒宣洩
- none：正常訊息

只回覆 JSON，不要加任何說明文字。"""


class RiskHandler:
    """偵測風險訊息並通知相關人員。"""

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
        self.admin_user_id = config.get("ADMIN_LINE_USER_ID", "")

    def handle(self, ctx: Dict[str, Any]) -> None:
        """分析風險並通知相關人員。"""
        text = ctx.get("text", "")
        group_id = ctx.get("group_id")
        reply_token = ctx.get("reply_token", "")

        # 1. LLM 風險分析
        risk_result = self._analyze_risk(text)
        risk_level = risk_result.get("riskLevel", "none")

        logger.info(
            "Risk analysis | level=%s | category=%s | group=%s",
            risk_level,
            risk_result.get("category"),
            group_id,
        )

        if risk_level == "none":
            return

        # 2. 記錄到 Notion AI Alerts
        self._save_alert_to_notion(risk_result, ctx)

        # 3. 通知管理員／老師
        if risk_result.get("shouldAlertTeacher") and self.admin_user_id:
            self._notify_admin(risk_result, ctx)

        # 4. 群組公開回覆（僅限 low 且允許公開）
        if (
            risk_result.get("publicReplyAllowed")
            and risk_level == "low"
            and reply_token
        ):
            public_reply = risk_result.get("suggestedPublicReply", "")
            if public_reply:
                self.line_api.reply(reply_token, public_reply)

        # high/medium 風險：群組中溫和安撫，不公開展開
        elif risk_level in ("high", "medium") and reply_token:
            if risk_level == "high":
                self.line_api.reply(
                    reply_token,
                    "我注意到您的訊息，已立即通知老師關心。\n"
                    "如果需要幫助，請不要猶豫，老師很快會與您聯繫。💙",
                )
            else:
                self.line_api.reply(
                    reply_token,
                    "感謝您的回饋，我已通知老師或行政老師協助處理。🙏",
                )

    def _analyze_risk(self, message: str) -> Dict[str, Any]:
        """使用 LLM 分析風險等級。"""
        import json

        prompt = RISK_ANALYSIS_PROMPT.format(message=message[:500])
        response = self.llm.chat(prompt)

        try:
            # 嘗試解析 JSON
            result = json.loads(response or "{}")
            return result
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse risk analysis JSON: %s", response)
            # 回傳保守預設值
            return {
                "riskLevel": "low",
                "category": "其他",
                "shouldAlertTeacher": True,
                "publicReplyAllowed": False,
                "suggestedPrivateAlert": "訊息需要人工確認",
                "suggestedPublicReply": "",
            }

    def _notify_admin(self, risk_result: Dict[str, Any], ctx: Dict[str, Any]) -> None:
        """推播通知給管理員。"""
        group_id = ctx.get("group_id", "未知群組")
        class_name = self.notion.get_class_name_by_group(group_id) if group_id else "未知班級"

        alert_msg = (
            f"⚠️ AI 班主任風險提醒\n"
            f"類型：{risk_result.get('category', '未知')}\n"
            f"等級：{risk_result.get('riskLevel', 'unknown')}\n"
            f"班級：{class_name}\n"
            f"摘要：{risk_result.get('suggestedPrivateAlert', '請查看 Notion AI Alerts')}"
        )

        try:
            self.line_api.push_message(self.admin_user_id, alert_msg)
            logger.info("Risk alert sent to admin: %s", self.admin_user_id)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to send risk alert to admin: %s", exc)

    def _save_alert_to_notion(
        self, risk_result: Dict[str, Any], ctx: Dict[str, Any]
    ) -> None:
        """將風險事件記錄到 Notion AI Alerts 資料庫。"""
        try:
            self.notion.create_ai_alert(
                title=f"{risk_result.get('category', '未知')}風險提醒",
                category=risk_result.get("category", "其他"),
                level=risk_result.get("riskLevel", "low"),
                group_id=ctx.get("group_id", ""),
                summary=risk_result.get("suggestedPrivateAlert", ""),
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to save AI alert to Notion: %s", exc)
