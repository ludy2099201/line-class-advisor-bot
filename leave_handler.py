"""
[4] leave-intake — 請假引導 Handler
群組中簡短引導，詳細資料轉私訊收集，避免在群組公開個資。
使用簡易狀態機管理私訊中的多輪對話。
"""
import logging
from typing import Any, Dict

from ..services.line_api import LineApiService
from ..services.notion_service import NotionService
from ..utils.session_store import SessionStore

logger = logging.getLogger(__name__)

# 請假對話狀態
STATE_INIT = "leave_init"
STATE_WAIT_NAME = "leave_wait_name"
STATE_WAIT_DATE = "leave_wait_date"
STATE_WAIT_REASON = "leave_wait_reason"
STATE_DONE = "leave_done"


class LeaveHandler:
    """處理請假與補課引導流程。"""

    def __init__(
        self,
        config: Dict[str, Any],
        line_api: LineApiService,
        notion: NotionService,
    ):
        self.config = config
        self.line_api = line_api
        self.notion = notion
        self.session = SessionStore()

    def handle(self, ctx: Dict[str, Any]) -> None:
        """根據來源（群組或私訊）決定處理方式。"""
        source_type = ctx.get("source_type", "")
        command = ctx.get("command", "")

        if source_type == "group":
            # 群組中只給引導訊息，不收集個資
            self._reply_group_guidance(ctx, command)
        else:
            # 私訊中進行多輪對話收集請假資訊
            self._handle_dm_flow(ctx)

    def _reply_group_guidance(self, ctx: Dict[str, Any], command: str) -> None:
        """群組中回覆引導訊息。"""
        reply_token = ctx["reply_token"]
        if command == "makeup_class":
            self.line_api.reply(
                reply_token,
                "補課申請可以協助處理。為避免在群組公開孩子個資，"
                "請私訊我「補課」，或由行政老師協助您確認。📋",
            )
        else:
            self.line_api.reply(
                reply_token,
                "可以，我先幫您引導請假流程。為避免在群組公開孩子個資，"
                "請私訊我「請假」，或稍後由行政老師協助您確認。📋",
            )

    def _handle_dm_flow(self, ctx: Dict[str, Any]) -> None:
        """私訊中的多輪請假對話流程。"""
        user_id = ctx["user_id"]
        reply_token = ctx["reply_token"]
        clean_text = ctx.get("clean_text", "").strip()

        state = self.session.get_state(user_id)

        if state is None or clean_text in ("請假", "補課"):
            # 開始新的請假流程
            self.session.set_state(user_id, STATE_WAIT_NAME, {})
            self.line_api.reply(reply_token, "好的，我來協助您登記請假。\n請問學生姓名？")

        elif state == STATE_WAIT_NAME:
            self.session.update_data(user_id, {"student_name": clean_text})
            self.session.set_state(user_id, STATE_WAIT_DATE)
            self.line_api.reply(reply_token, f"謝謝！請問 {clean_text} 的請假日期？\n（格式：MM/DD，例如 05/10）")

        elif state == STATE_WAIT_DATE:
            self.session.update_data(user_id, {"leave_date": clean_text})
            self.session.set_state(user_id, STATE_WAIT_REASON)
            self.line_api.reply(
                reply_token,
                "請簡短填寫請假原因，或輸入「略過」跳過此步驟。\n"
                "（原因僅供行政老師參考，不會公開）",
            )

        elif state == STATE_WAIT_REASON:
            reason = clean_text if clean_text != "略過" else ""
            data = self.session.get_data(user_id)
            data["reason"] = reason

            # 寫入 Notion
            success = self._save_leave_to_notion(data, user_id)

            self.session.clear(user_id)

            if success:
                self.line_api.reply(
                    reply_token,
                    f"✅ 已收到請假需求！\n"
                    f"學生：{data.get('student_name', '')}\n"
                    f"日期：{data.get('leave_date', '')}\n\n"
                    "我會通知行政老師確認補課安排，稍後會有專人與您聯繫。",
                )
            else:
                self.line_api.reply(
                    reply_token,
                    "請假資訊已收到，但系統登記時發生問題。\n"
                    "請直接聯繫行政老師確認，造成不便非常抱歉。🙏",
                )
        else:
            # 未知狀態，重置
            self.session.clear(user_id)
            self.line_api.reply(
                reply_token,
                "請輸入「請假」開始請假流程，或聯繫行政老師協助。",
            )

    def _save_leave_to_notion(self, data: Dict[str, Any], user_id: str) -> bool:
        """將請假資料寫入 Notion Leaves 資料庫。"""
        try:
            self.notion.create_leave_record(
                student_name=data.get("student_name", ""),
                leave_date=data.get("leave_date", ""),
                reason=data.get("reason", ""),
                source="LINE",
                user_id_hash=self._hash_user_id(user_id),
            )
            return True
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to save leave record to Notion: %s", exc)
            return False

    @staticmethod
    def _hash_user_id(user_id: str) -> str:
        """對 userId 進行 hash，避免儲存原始個資。"""
        import hashlib
        return hashlib.sha256(user_id.encode()).hexdigest()[:16]
