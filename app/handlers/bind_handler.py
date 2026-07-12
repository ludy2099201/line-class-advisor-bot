"""
[6] bind-group — 群組綁定班級 Handler

老師在群組中輸入「綁定班級」，Bot 列出所有開課中的班級供選擇，
確認後將 LINE groupId 寫入 Notion LINE Groups 資料庫。

流程：
  Step 1: 老師輸入「綁定班級」→ Bot 列出班級清單（最多 20 班）
  Step 2: 老師輸入班級編號 → Bot 確認選擇
  Step 3: 老師輸入「確認」→ 寫入 Notion，完成綁定

注意：此功能僅限群組使用，私訊無效。
"""
import logging
from typing import Any, Dict, List

from ..services.line_api import LineApiService
from ..services.notion_service import NotionService
from ..utils.session_store import SessionStore

logger = logging.getLogger(__name__)

# Session 狀態鍵
_STATE = "bind_state"
_CLASSES = "bind_classes"
_SELECTED = "bind_selected"


class BindHandler:
    """處理群組綁定班級的多輪對話。"""

    def __init__(
        self,
        config: Dict[str, Any],
        line_api: LineApiService,
        notion: NotionService,
        session: SessionStore,
    ):
        self.config = config
        self.line_api = line_api
        self.notion = notion
        self.session = session

    # ── 入口 ─────────────────────────────────────────────────────────────────

    def handle_start(self, ctx: Dict[str, Any]) -> None:
        """處理「綁定班級」指令入口（僅限群組）。"""
        reply_token = ctx["reply_token"]
        group_id = ctx.get("group_id")
        user_id = ctx.get("user_id", "")

        if not group_id:
            self.line_api.reply(
                reply_token,
                "⚠️ 此功能僅限在群組中使用。\n請在班級群組中輸入「綁定班級」。",
            )
            return

        # 取得班級清單
        classes = self.notion.list_classes()
        if not classes:
            self.line_api.reply(
                reply_token,
                "⚠️ 目前沒有開課中的班級資料。\n請先在 Notion 班級資料庫中新增班級，並勾選「開課中」。",
            )
            return

        # 儲存班級清單到 session（以 group_id 為 key）
        session_key = f"bind_{group_id}"
        self.session.set(session_key, {_STATE: "selecting", _CLASSES: classes})

        # 格式化班級選單
        lines = ["📋 請選擇要綁定的班級（輸入編號）：\n"]
        for i, cls in enumerate(classes[:20], 1):
            name = cls["name"]
            days = cls.get("days", "")
            time_slot = cls.get("time_slot", "")
            detail = ""
            if days:
                detail += f"週{days}"
            if time_slot:
                detail += f" {time_slot}"
            lines.append(f"{i}. {name}" + (f"（{detail}）" if detail else ""))
        lines.append("\n輸入「取消」可中止操作。")

        self.line_api.reply(reply_token, "\n".join(lines))
        logger.info("BindHandler: started for group %s, %d classes listed", group_id[:8], len(classes))

    def handle_step(self, ctx: Dict[str, Any]) -> bool:
        """處理綁定流程中的後續輸入。
        
        回傳 True 表示此訊息已被本 handler 處理（router 不需再繼續路由）。
        回傳 False 表示不在綁定流程中，router 應繼續其他路由。
        """
        group_id = ctx.get("group_id")
        if not group_id:
            return False

        session_key = f"bind_{group_id}"
        data = self.session.get(session_key)
        if not data or data.get(_STATE) not in ("selecting", "confirming"):
            return False

        text = ctx.get("clean_text", "").strip()
        reply_token = ctx["reply_token"]

        # 取消
        if text in ("取消", "cancel", "Cancel"):
            self.session.clear(session_key)
            self.line_api.reply(reply_token, "已取消綁定操作。")
            return True

        state = data.get(_STATE)

        if state == "selecting":
            return self._handle_selection(ctx, data, session_key, text)
        elif state == "confirming":
            return self._handle_confirmation(ctx, data, session_key, text)

        return False

    # ── 私有方法 ─────────────────────────────────────────────────────────────

    def _handle_selection(
        self,
        ctx: Dict[str, Any],
        data: Dict,
        session_key: str,
        text: str,
    ) -> bool:
        """處理班級編號選擇。"""
        reply_token = ctx["reply_token"]
        classes: List[Dict] = data.get(_CLASSES, [])

        try:
            idx = int(text) - 1
            if not (0 <= idx < len(classes)):
                raise ValueError("out of range")
        except (ValueError, TypeError):
            self.line_api.reply(
                reply_token,
                f"⚠️ 請輸入有效的班級編號（1–{len(classes)}），或輸入「取消」中止。",
            )
            return True

        selected = classes[idx]
        data[_STATE] = "confirming"
        data[_SELECTED] = selected
        self.session.set(session_key, data)

        name = selected["name"]
        days = selected.get("days", "")
        time_slot = selected.get("time_slot", "")
        detail = f"週{days} {time_slot}".strip() if days else time_slot

        confirm_msg = (
            f"✅ 您選擇了：\n"
            f"班級：{name}\n"
        )
        if detail:
            confirm_msg += f"時段：{detail}\n"
        confirm_msg += "\n確認要將此群組綁定到這個班級嗎？\n輸入「確認」完成綁定，或「取消」重新選擇。"

        self.line_api.reply(reply_token, confirm_msg)
        return True

    def _handle_confirmation(
        self,
        ctx: Dict[str, Any],
        data: Dict,
        session_key: str,
        text: str,
    ) -> bool:
        """處理最終確認。"""
        reply_token = ctx["reply_token"]
        group_id = ctx.get("group_id", "")

        if text not in ("確認", "confirm", "Confirm", "yes", "是"):
            # 非確認詞，視為重新選擇
            data[_STATE] = "selecting"
            data.pop(_SELECTED, None)
            self.session.set(session_key, data)

            classes = data.get(_CLASSES, [])
            lines = ["請重新輸入班級編號：\n"]
            for i, cls in enumerate(classes[:20], 1):
                lines.append(f"{i}. {cls['name']}")
            lines.append("\n輸入「取消」可中止操作。")
            self.line_api.reply(reply_token, "\n".join(lines))
            return True

        selected = data.get(_SELECTED, {})
        class_name = selected.get("name", "")

        # 取得群組名稱（LINE API 無法直接取得，使用班級名稱作為群組名稱）
        group_name = f"慕熙補習班 - {class_name}群組"

        # 寫入 Notion
        success = self.notion.bind_group_to_class(group_id, group_name, class_name)
        self.session.clear(session_key)

        if success:
            self.line_api.reply(
                reply_token,
                f"🎉 綁定成功！\n\n"
                f"此群組已綁定到「{class_name}」。\n"
                f"之後在此群組查詢「今日課表」、「今日作業」等，\n"
                f"Bot 將自動顯示 {class_name} 的專屬資訊。",
            )
            logger.info(
                "BindHandler: group %s successfully bound to class %s",
                group_id[:8],
                class_name,
            )
        else:
            self.line_api.reply(
                reply_token,
                "⚠️ 綁定時發生錯誤，請稍後再試或聯繫管理員。",
            )
            logger.error(
                "BindHandler: failed to bind group %s to class %s",
                group_id[:8],
                class_name,
            )

        return True
