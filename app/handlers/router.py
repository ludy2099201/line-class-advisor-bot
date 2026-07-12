"""
[0] line-router — LINE 訊息路由核心
解析事件、判斷身份、分流至各功能 Handler。

設計原則：
- 群組中「少說話」比「聰明」重要
- 只在明確被 @AI班主任 或輸入指定指令時才回覆
- 不在群組公開個資
"""
import logging
import re
from typing import Any, Dict, Optional

from ..services.line_api import LineApiService
from ..services.notion_service import NotionService
from ..utils.session_store import SessionStore
from .faq_handler import FaqHandler
from .schedule_handler import ScheduleHandler
from .homework_handler import HomeworkHandler
from .leave_handler import LeaveHandler
from .risk_handler import RiskHandler
from .bind_handler import BindHandler
from .note_handler import NoteHandler

logger = logging.getLogger(__name__)

# ── MVP 開放指令清單 ──────────────────────────────────────────────────────────
COMMANDS = {
    "今日課表": "schedule_today",
    "明日課表": "schedule_tomorrow",
    "今日作業": "homework_today",
    "明日作業": "homework_tomorrow",
    "考試範圍": "exam_query",
    "請假": "leave",
    "補課": "makeup_class",
    "學費": "faq",
    "上課時間": "faq",
    "綁定班級": "bind_class",       # 新增：群組綁定班級
    "查詢綁定": "check_binding",    # 新增：查詢目前群組綁定狀態
    "課後筆記": "note_create",       # 新增：老師課後筆記記錄
    "記錄筆記": "note_create",       # 新增：老師課後筆記記錄（別名）
    "筆記列表": "note_list_today",   # 新增：今日筆記列表
}

# 個資相關關鍵字，群組中不公開回覆
PRIVACY_KEYWORDS = [
    "成績", "排名", "分數", "學費", "繳費", "付款", "匯款",
    "電話", "地址", "帳號", "密碼", "請假原因",
]

# 風險訊號關鍵字（初步過濾，詳細判斷交由 RiskHandler）
RISK_KEYWORDS = [
    "不想活", "受不了", "想死", "霸凌", "打人", "威脅",
    "客訴", "投訴", "告你", "沒有處理", "都沒人管",
]


class LineRouter:
    """LINE 訊息路由器，負責解析事件並分流至對應 Handler。"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.line_api = LineApiService(config)
        self.notion = NotionService(config)
        self.session = SessionStore()
        self.faq_handler = FaqHandler(config, self.line_api, self.notion)
        self.schedule_handler = ScheduleHandler(config, self.line_api, self.notion)
        self.homework_handler = HomeworkHandler(config, self.line_api, self.notion)
        self.leave_handler = LeaveHandler(config, self.line_api, self.notion)
        self.risk_handler = RiskHandler(config, self.line_api, self.notion)
        self.bind_handler = BindHandler(config, self.line_api, self.notion, self.session)
        self.note_handler = NoteHandler(self.session)

    def handle(self, event: Dict[str, Any]) -> None:
        """處理單一 LINE 事件。"""
        event_type = event.get("type")
        if event_type != "message":
            return  # 目前只處理訊息事件

        message = event.get("message", {})
        msg_type = message.get("type")

        if msg_type == "text":
            self._handle_text_event(event)
        elif msg_type == "image":
            # 圖片處理為第二階段功能，目前僅記錄
            logger.info("Image message received, skipped in MVP")
        else:
            logger.debug("Unsupported message type: %s", msg_type)

    def _handle_text_event(self, event: Dict[str, Any]) -> None:
        """處理文字訊息事件。"""
        message = event.get("message", {})
        text: str = message.get("text", "").strip()
        reply_token: str = event.get("replyToken", "")
        source = event.get("source", {})
        source_type: str = source.get("type", "")
        user_id: str = source.get("userId", "")
        group_id: Optional[str] = source.get("groupId")

        # 解析路由上下文
        ctx = self._parse_context(
            text=text,
            source_type=source_type,
            user_id=user_id,
            group_id=group_id,
            reply_token=reply_token,
        )

        logger.info(
            "Event parsed | source=%s | command=%s | mentioned=%s | risk=%s | privacy=%s",
            source_type,
            ctx.get("command"),
            ctx.get("is_mentioned"),
            ctx.get("is_risk_candidate"),
            ctx.get("is_privacy_candidate"),
        )

        # ── 優先：檢查是否在綁定流程中（多輪對話） ──────────────────────────
        if group_id and self.bind_handler.handle_step(ctx):
            return  # 已被 bind_handler 處理，不繼續路由

        # ── 優先：檢查是否在課後筆記流程中（多輪對話） ─────────────────────────
        note_reply = self.note_handler.handle_step(user_id, text)
        if note_reply is not None:
            self.line_api.reply(reply_token, note_reply)
            return

        # ── 優先：檢查是否在請假流程中（多輪對話） ──────────────────────────
        if self.leave_handler.is_in_session(ctx):
            self.leave_handler.handle(ctx)
            return

        # ── 風險偵測（優先，不受靜默規則限制）──────────────────────────────
        if ctx["is_risk_candidate"]:
            self.risk_handler.handle(ctx)
            # 風險訊息在群組中不公開展開，直接返回
            if source_type == "group":
                return

        # ── 靜默規則：群組中不符合條件則不回覆 ─────────────────────────────
        if source_type == "group" and not ctx["should_reply"]:
            logger.debug("Silent: group message does not match any trigger")
            return

        # ── 個資保護：群組中涉及個資則引導私訊 ─────────────────────────────
        if source_type == "group" and ctx["is_privacy_candidate"]:
            self.line_api.reply(
                reply_token,
                "這類資訊涉及個人資料，我先不在群組公開回覆。\n"
                "請私訊老師或行政老師協助確認。🔒",
            )
            return

        # ── 依指令分流 ────────────────────────────────────────────────────────
        command = ctx.get("command")

        if command == "schedule_today":
            self.schedule_handler.handle_today(ctx)
        elif command == "schedule_tomorrow":
            self.schedule_handler.handle_tomorrow(ctx)
        elif command == "homework_today":
            self.homework_handler.handle_today(ctx)
        elif command == "homework_tomorrow":
            self.homework_handler.handle_tomorrow(ctx)
        elif command == "exam_query":
            self.homework_handler.handle_exam(ctx)
        elif command in ("leave", "makeup_class"):
            self.leave_handler.handle(ctx)
        elif command == "bind_class":
            self.bind_handler.handle_start(ctx)
        elif command == "check_binding":
            self._handle_check_binding(ctx)
        elif command == "note_create":
            self._handle_note_create(ctx)
        elif command == "note_list_today":
            self._handle_note_list_today(ctx)
        elif text.startswith("查詢筆記"):
            self._handle_note_query(ctx)
        elif command == "faq":
            self.faq_handler.handle(ctx)
        elif ctx["is_mentioned"] or source_type == "user":
            # 被 @AI班主任 但沒有明確指令，或私訊，交由 FAQ 嘗試回答
            self.faq_handler.handle(ctx)
        else:
            logger.debug("No matching handler for command: %s", command)

    def _handle_check_binding(self, ctx: Dict[str, Any]) -> None:
        """查詢目前群組的班級綁定狀態。"""
        reply_token = ctx["reply_token"]
        group_id = ctx.get("group_id")

        if not group_id:
            self.line_api.reply(reply_token, "此功能僅限群組使用。")
            return

        class_name = self.notion.get_class_id_by_group(group_id)
        group_display_name = self.notion.get_class_name_by_group(group_id)

        if class_name:
            self.line_api.reply(
                reply_token,
                f"📌 此群組目前綁定狀態：\n"
                f"群組名稱：{group_display_name}\n"
                f"對應班級：{class_name}\n\n"
                f"查詢「今日課表」、「今日作業」等指令時，\n"
                f"Bot 將自動顯示 {class_name} 的專屬資訊。\n\n"
                f"如需重新綁定，請輸入「綁定班級」。",
            )
        else:
            self.line_api.reply(
                reply_token,
                "📌 此群組尚未綁定班級。\n\n"
                "輸入「綁定班級」開始設定，\n"
                "綁定後查詢課表和作業時將顯示該班級的專屬資訊。",
            )

    def _parse_context(
        self,
        text: str,
        source_type: str,
        user_id: str,
        group_id: Optional[str],
        reply_token: str,
    ) -> Dict[str, Any]:
        """解析訊息，產生路由所需的上下文字典。"""
        bot_name = self.config.get("BOT_NAME", "AI班主任")

        # 是否被 @AI班主任 提及
        is_mentioned = f"@{bot_name}" in text

        # 移除 @AI班主任 後的純文字
        clean_text = re.sub(rf"@{re.escape(bot_name)}", "", text).strip()

        # 比對指令
        command = None
        for keyword, cmd in COMMANDS.items():
            if keyword in clean_text:
                command = cmd
                break

        # 是否為指令
        is_command = command is not None

        # 個資候選
        is_privacy_candidate = any(kw in clean_text for kw in PRIVACY_KEYWORDS)

        # 風險候選
        is_risk_candidate = any(kw in clean_text for kw in RISK_KEYWORDS)

        # 是否應該回覆（群組靜默規則）
        if source_type == "group":
            should_reply = is_mentioned or is_command or is_risk_candidate
        else:
            # 私訊一律回覆
            should_reply = True

        return {
            "text": text,
            "clean_text": clean_text,
            "reply_token": reply_token,
            "user_id": user_id,
            "group_id": group_id,
            "source_type": source_type,
            "is_mentioned": is_mentioned,
            "is_command": is_command,
            "command": command,
            "is_risk_candidate": is_risk_candidate,
            "is_privacy_candidate": is_privacy_candidate,
            "should_reply": should_reply,
        }

    def _handle_note_create(self, ctx: Dict[str, Any]) -> None:
        """啟動課後筆記記錄流程。"""
        user_id = ctx["user_id"]
        reply_token = ctx["reply_token"]
        first_reply = self.note_handler.start_note(user_id)
        self.line_api.reply(reply_token, first_reply)

    def _handle_note_list_today(self, ctx: Dict[str, Any]) -> None:
        """列出今日所有課後筆記。"""
        from datetime import date
        reply_token = ctx["reply_token"]
        today = date.today().isoformat()
        notes = self.notion.get_notes_by_date(today)
        if not notes:
            self.line_api.reply(reply_token, f"📓 今日（{today}）尚無課後筆記。")
            return
        lines = [f"📓 今日課後筆記（共 {len(notes)} 筆）\n"]
        for i, n in enumerate(notes, 1):
            perf = f"【{n['performance']}】" if n.get("performance") else ""
            emo = f"😊{n['emotion']}" if n.get("emotion") else ""
            lines.append(
                f"{i}. {n['student']} {perf}{emo}\n"
                f"   課程：{n.get('course', '—')}\n"
                f"   {n.get('content', '')[:50]}"
            )
            if n.get("followup"):
                lines.append(f"   🔔 追蹤：{n['followup'][:30]}")
        self.line_api.reply(reply_token, "\n".join(lines))

    def _handle_note_query(self, ctx: Dict[str, Any]) -> None:
        """查詢特定學生的歷史課後筆記。格式：查詢筆記 學生姓名"""
        reply_token = ctx["reply_token"]
        text = ctx["text"]
        # 解析學生姓名：「查詢筆記 王小明」
        parts = text.replace("查詢筆記", "").strip()
        if not parts:
            self.line_api.reply(
                reply_token,
                "請輸入學生姓名，例如：\n查詢筆記 王小明"
            )
            return
        student_name = parts
        notes = self.notion.get_student_notes(student_name, limit=5)
        if not notes:
            self.line_api.reply(reply_token, f"📓 找不到「{student_name}」的課後筆記。")
            return
        lines = [f"📓 {student_name} 的最近 {len(notes)} 筆課後筆記\n"]
        for n in notes:
            perf = f"【{n['performance']}】" if n.get("performance") else ""
            emo = f" {n['emotion']}" if n.get("emotion") else ""
            lines.append(
                f"📅 {n['date']} {n.get('course', '')} {perf}{emo}\n"
                f"   {n.get('content', '')[:80]}"
            )
            if n.get("followup"):
                lines.append(f"   🔔 追蹤：{n['followup'][:40]}")
            lines.append("")
        self.line_api.reply(reply_token, "\n".join(lines).strip())
