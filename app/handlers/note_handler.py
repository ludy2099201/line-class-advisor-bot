"""
課後筆記 Handler
老師可透過 LINE 快速記錄課後觀察，並查詢特定學生的歷史筆記。

指令：
  「課後筆記」/ 「記錄筆記」 → 開始新增筆記流程
  「查詢筆記 <學生名>」       → 查詢該學生的歷史筆記
  「筆記列表」                → 查詢今日所有筆記
"""

import logging
from datetime import date, datetime
from typing import Optional

from ..services import notion_service as notion
from ..utils.session_store import SessionStore

logger = logging.getLogger(__name__)

# 筆記新增流程的步驟定義
NOTE_STEPS = ["student", "course", "performance", "emotion", "content", "followup", "confirm"]

PERFORMANCE_OPTIONS = ["優秀", "良好", "普通", "需加強", "需關注"]
EMOTION_OPTIONS = ["開心", "平穩", "疲憊", "焦慮", "低落"]

PERFORMANCE_EMOJI = {
    "優秀": "🌟", "良好": "✅", "普通": "📖", "需加強": "⚠️", "需關注": "🚨"
}
EMOTION_EMOJI = {
    "開心": "😊", "平穩": "😐", "疲憊": "😴", "焦慮": "😟", "低落": "😔"
}


class NoteHandler:
    def __init__(self, session_store: SessionStore):
        self.session = session_store

    # ─────────────────────────────────────────────
    # 公開入口
    # ─────────────────────────────────────────────

    def start_note(self, user_id: str, display_name: str = "") -> str:
        """開始新增課後筆記流程"""
        self.session.set(user_id, {
            "mode": "note_create",
            "step": "student",
            "teacher": display_name or "老師",
            "data": {}
        })
        return (
            "📓 **課後筆記記錄**\n\n"
            "請輸入學生姓名（可輸入中文名或英文名）：\n"
            "（輸入「取消」可隨時結束）"
        )

    def handle_step(self, user_id: str, text: str) -> Optional[str]:
        """處理多輪對話步驟，回傳 None 表示此訊息不屬於筆記流程"""
        state = self.session.get(user_id)
        if not state or state.get("mode") != "note_create":
            return None

        # 取消指令
        if text.strip() in ["取消", "cancel", "Cancel"]:
            self.session.delete(user_id)
            return "❌ 已取消課後筆記記錄。"

        step = state.get("step")

        if step == "student":
            return self._handle_student(user_id, state, text)
        elif step == "course":
            return self._handle_course(user_id, state, text)
        elif step == "performance":
            return self._handle_performance(user_id, state, text)
        elif step == "emotion":
            return self._handle_emotion(user_id, state, text)
        elif step == "content":
            return self._handle_content(user_id, state, text)
        elif step == "followup":
            return self._handle_followup(user_id, state, text)
        elif step == "confirm":
            return self._handle_confirm(user_id, state, text)

        return None

    def query_student_notes(self, student_name: str, limit: int = 5) -> str:
        """查詢特定學生的歷史筆記"""
        try:
            notes = notion.get_student_notes(student_name, limit)
            if not notes:
                return f"📓 找不到「{student_name}」的課後筆記記錄。"

            lines = [f"📓 **{student_name} 的最近 {len(notes)} 筆記錄**\n"]
            for note in notes:
                date_str = note.get("date", "未知日期")
                course = note.get("course", "未知課程")
                perf = note.get("performance", "")
                emotion = note.get("emotion", "")
                content = note.get("content", "（無內容）")
                followup = note.get("followup", "")
                teacher = note.get("teacher", "")

                perf_icon = PERFORMANCE_EMOJI.get(perf, "")
                emo_icon = EMOTION_EMOJI.get(emotion, "")

                lines.append(f"📅 {date_str} ｜ {course}")
                lines.append(f"  表現：{perf_icon}{perf}　情緒：{emo_icon}{emotion}")
                lines.append(f"  {content}")
                if followup:
                    lines.append(f"  ⚠️ 追蹤：{followup}")
                if teacher:
                    lines.append(f"  👨‍🏫 記錄者：{teacher}")
                lines.append("")

            return "\n".join(lines).strip()

        except Exception as e:
            logger.error(f"查詢學生筆記失敗: {e}")
            return "⚠️ 查詢筆記時發生錯誤，請稍後再試。"

    def query_today_notes(self) -> str:
        """查詢今日所有課後筆記"""
        try:
            today = date.today().isoformat()
            notes = notion.get_notes_by_date(today)
            if not notes:
                return f"📓 今日（{today}）尚無課後筆記記錄。"

            lines = [f"📓 **今日課後筆記（共 {len(notes)} 筆）**\n"]
            for note in notes:
                student = note.get("student", "未知學生")
                course = note.get("course", "")
                perf = note.get("performance", "")
                emotion = note.get("emotion", "")
                content = note.get("content", "")
                followup = note.get("followup", "")

                perf_icon = PERFORMANCE_EMOJI.get(perf, "")
                emo_icon = EMOTION_EMOJI.get(emotion, "")

                lines.append(f"👤 **{student}**｜{course}")
                lines.append(f"  {perf_icon}{perf}　{emo_icon}{emotion}")
                if content:
                    lines.append(f"  {content[:50]}{'...' if len(content) > 50 else ''}")
                if followup:
                    lines.append(f"  ⚠️ {followup}")
                lines.append("")

            return "\n".join(lines).strip()

        except Exception as e:
            logger.error(f"查詢今日筆記失敗: {e}")
            return "⚠️ 查詢今日筆記時發生錯誤，請稍後再試。"

    # ─────────────────────────────────────────────
    # 私有步驟處理
    # ─────────────────────────────────────────────

    def _handle_student(self, user_id: str, state: dict, text: str) -> str:
        state["data"]["student"] = text.strip()
        state["step"] = "course"
        self.session.set(user_id, state)
        return (
            f"✅ 學生：{text.strip()}\n\n"
            "請輸入課程名稱（例如：Fall 一三班、Summer Workshop Art）：\n"
            "（或輸入「略過」跳過）"
        )

    def _handle_course(self, user_id: str, state: dict, text: str) -> str:
        if text.strip() not in ["略過", "skip"]:
            state["data"]["course"] = text.strip()
        state["step"] = "performance"
        self.session.set(user_id, state)

        options = "\n".join(
            [f"{i+1}. {PERFORMANCE_EMOJI[opt]}{opt}" for i, opt in enumerate(PERFORMANCE_OPTIONS)]
        )
        return (
            "請選擇學習表現（輸入數字）：\n\n"
            f"{options}"
        )

    def _handle_performance(self, user_id: str, state: dict, text: str) -> str:
        text = text.strip()
        # 支援數字或直接輸入文字
        if text.isdigit() and 1 <= int(text) <= len(PERFORMANCE_OPTIONS):
            perf = PERFORMANCE_OPTIONS[int(text) - 1]
        elif text in PERFORMANCE_OPTIONS:
            perf = text
        else:
            options = "\n".join(
                [f"{i+1}. {PERFORMANCE_EMOJI[opt]}{opt}" for i, opt in enumerate(PERFORMANCE_OPTIONS)]
            )
            return f"請輸入 1–{len(PERFORMANCE_OPTIONS)} 的數字，或直接輸入選項文字：\n\n{options}"

        state["data"]["performance"] = perf
        state["step"] = "emotion"
        self.session.set(user_id, state)

        options = "\n".join(
            [f"{i+1}. {EMOTION_EMOJI[opt]}{opt}" for i, opt in enumerate(EMOTION_OPTIONS)]
        )
        return (
            f"✅ 學習表現：{PERFORMANCE_EMOJI[perf]}{perf}\n\n"
            "請選擇情緒狀態（輸入數字）：\n\n"
            f"{options}"
        )

    def _handle_emotion(self, user_id: str, state: dict, text: str) -> str:
        text = text.strip()
        if text.isdigit() and 1 <= int(text) <= len(EMOTION_OPTIONS):
            emo = EMOTION_OPTIONS[int(text) - 1]
        elif text in EMOTION_OPTIONS:
            emo = text
        else:
            options = "\n".join(
                [f"{i+1}. {EMOTION_EMOJI[opt]}{opt}" for i, opt in enumerate(EMOTION_OPTIONS)]
            )
            return f"請輸入 1–{len(EMOTION_OPTIONS)} 的數字，或直接輸入選項文字：\n\n{options}"

        state["data"]["emotion"] = emo
        state["step"] = "content"
        self.session.set(user_id, state)
        return (
            f"✅ 情緒狀態：{EMOTION_EMOJI[emo]}{emo}\n\n"
            "請輸入課後觀察筆記內容：\n"
            "（描述本堂課的學習狀況、特別表現或需要注意的事項）"
        )

    def _handle_content(self, user_id: str, state: dict, text: str) -> str:
        state["data"]["content"] = text.strip()
        state["step"] = "followup"
        self.session.set(user_id, state)
        return (
            "是否有需要追蹤的事項？\n"
            "（例如：需要補交作業、需要家長配合、下次課程重點等）\n"
            "（輸入「略過」跳過）"
        )

    def _handle_followup(self, user_id: str, state: dict, text: str) -> str:
        if text.strip() not in ["略過", "skip"]:
            state["data"]["followup"] = text.strip()
        state["step"] = "confirm"
        self.session.set(user_id, state)

        data = state["data"]
        student = data.get("student", "未填")
        course = data.get("course", "未填")
        perf = data.get("performance", "未填")
        emo = data.get("emotion", "未填")
        content = data.get("content", "未填")
        followup = data.get("followup", "（無）")

        return (
            "📋 **請確認筆記內容**\n\n"
            f"👤 學生：{student}\n"
            f"📚 課程：{course}\n"
            f"🌟 學習表現：{PERFORMANCE_EMOJI.get(perf, '')}{perf}\n"
            f"😊 情緒狀態：{EMOTION_EMOJI.get(emo, '')}{emo}\n"
            f"📝 筆記內容：{content}\n"
            f"⚠️ 追蹤事項：{followup}\n\n"
            "輸入「確認」儲存，或「取消」放棄。"
        )

    def _handle_confirm(self, user_id: str, state: dict, text: str) -> str:
        if text.strip() not in ["確認", "confirm", "是", "yes"]:
            if text.strip() in ["取消", "cancel", "否", "no"]:
                self.session.delete(user_id)
                return "❌ 已取消，筆記未儲存。"
            return "請輸入「確認」儲存筆記，或「取消」放棄。"

        data = state["data"]
        teacher = state.get("teacher", "老師")
        today = date.today().isoformat()

        student = data.get("student", "")
        course = data.get("course", "")
        perf = data.get("performance", "")
        emo = data.get("emotion", "")
        content = data.get("content", "")
        followup = data.get("followup", "")

        # 產生筆記標題
        title = f"{today} {student} 課後筆記"

        try:
            notion.create_note(
                title=title,
                student=student,
                date=today,
                course=course,
                teacher=teacher,
                performance=perf,
                emotion=emo,
                content=content,
                followup=followup,
                recorder_user_id=user_id
            )
            self.session.delete(user_id)

            # 若有需要追蹤的事項，加強提醒
            followup_reminder = ""
            if followup:
                followup_reminder = f"\n\n⚠️ 追蹤提醒：{followup}"

            return (
                f"✅ **課後筆記已儲存！**\n\n"
                f"👤 {student}｜{today}\n"
                f"{PERFORMANCE_EMOJI.get(perf, '')}{perf}　{EMOTION_EMOJI.get(emo, '')}{emo}"
                f"{followup_reminder}"
            )

        except Exception as e:
            logger.error(f"儲存課後筆記失敗: {e}")
            self.session.delete(user_id)
            return "⚠️ 儲存筆記時發生錯誤，請稍後再試或手動記錄到 Notion。"
