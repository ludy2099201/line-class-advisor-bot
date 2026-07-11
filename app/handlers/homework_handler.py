"""
[3] homework-query — 作業與考試查詢 Handler
查詢今日／明日作業及本週考試範圍。
"""
import logging
from datetime import date, timedelta
from typing import Any, Dict

from ..services.line_api import LineApiService
from ..services.notion_service import NotionService

logger = logging.getLogger(__name__)


class HomeworkHandler:
    """處理作業查詢與考試範圍查詢。"""

    def __init__(
        self,
        config: Dict[str, Any],
        line_api: LineApiService,
        notion: NotionService,
    ):
        self.config = config
        self.line_api = line_api
        self.notion = notion

    def handle_today(self, ctx: Dict[str, Any]) -> None:
        """回覆今日截止作業。"""
        target_date = date.today()
        self._reply_homework(ctx, target_date, "今日")

    def handle_tomorrow(self, ctx: Dict[str, Any]) -> None:
        """回覆明日截止作業。"""
        target_date = date.today() + timedelta(days=1)
        self._reply_homework(ctx, target_date, "明日")

    def handle_exam(self, ctx: Dict[str, Any]) -> None:
        """回覆本週考試範圍。"""
        reply_token = ctx["reply_token"]
        group_id = ctx.get("group_id")

        class_id = self.notion.get_class_id_by_group(group_id) if group_id else None
        exams = self.notion.query_exams_this_week(class_id)

        if not exams:
            self.line_api.reply(
                reply_token,
                "🧪 本週考試提醒\n目前沒有登記本週的考試資料。",
            )
            return

        lines = ["🧪 本週考試提醒"]
        for exam in exams:
            exam_date = exam.get("exam_date", "")
            subject = exam.get("subject", "")
            scope = exam.get("scope", "")
            note = exam.get("note", "")

            line = f"{exam_date} {subject}考試"
            if scope:
                line += f"：{scope}"
            if note:
                line += f"\n提醒：{note}"
            lines.append(line)

        self.line_api.reply(reply_token, "\n\n".join(lines))

    def _reply_homework(
        self, ctx: Dict[str, Any], target_date: date, label: str
    ) -> None:
        """查詢作業並回覆。"""
        reply_token = ctx["reply_token"]
        group_id = ctx.get("group_id")

        class_id = self.notion.get_class_id_by_group(group_id) if group_id else None
        homework_list = self.notion.query_homework(target_date, class_id)

        if not homework_list:
            self.line_api.reply(
                reply_token,
                f"📝 {label}作業\n目前沒有登記 {target_date.strftime('%m/%d')} 的作業資料。",
            )
            return

        lines = [f"📝 {label}作業（截止 {target_date.strftime('%m/%d')}）"]
        for hw in homework_list:
            subject = hw.get("subject", "")
            content = hw.get("content", "")
            note = hw.get("note", "")

            line = f"{subject}：{content}"
            if note:
                line += f"\n提醒：{note}"
            lines.append(line)

        self.line_api.reply(reply_token, "\n\n".join(lines))
