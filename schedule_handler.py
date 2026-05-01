"""
[2] schedule-query — 課表查詢 Handler
依群組對應班級查詢今日或明日課表。
"""
import logging
from datetime import date, timedelta
from typing import Any, Dict, List

from ..services.line_api import LineApiService
from ..services.notion_service import NotionService

logger = logging.getLogger(__name__)


class ScheduleHandler:
    """處理今日／明日課表查詢。"""

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
        """回覆今日課表。"""
        target_date = date.today()
        self._reply_schedule(ctx, target_date, "今日")

    def handle_tomorrow(self, ctx: Dict[str, Any]) -> None:
        """回覆明日課表。"""
        target_date = date.today() + timedelta(days=1)
        self._reply_schedule(ctx, target_date, "明日")

    def _reply_schedule(
        self, ctx: Dict[str, Any], target_date: date, label: str
    ) -> None:
        """查詢課表並回覆。"""
        reply_token = ctx["reply_token"]
        group_id = ctx.get("group_id")

        # 1. 從 LINE Groups 資料庫取得對應班級
        class_id = self.notion.get_class_id_by_group(group_id) if group_id else None

        # 2. 查詢課表
        schedules = self.notion.query_schedule(target_date, class_id)

        if not schedules:
            self.line_api.reply(
                reply_token,
                f"📅 {label}課表\n目前沒有登記 {target_date.strftime('%m/%d')} 的課程資料。",
            )
            return

        # 3. 格式化回覆
        lines = [f"📅 {label}課表（{target_date.strftime('%m/%d')}）"]
        for s in schedules:
            time_range = s.get("time_range", "")
            class_name = s.get("class_name", "")
            room = s.get("room", "")
            note = s.get("note", "")

            line = f"{time_range} {class_name}"
            if room:
                line += f"\n教室：{room}"
            if note:
                line += f"\n提醒：{note}"
            lines.append(line)

        self.line_api.reply(reply_token, "\n\n".join(lines))
