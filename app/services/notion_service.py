"""
Notion API 服務封裝
提供查詢 FAQ、課表、作業、考試、請假、群組對應等功能。
"""
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionService:
    """封裝 Notion API 操作。"""

    def __init__(self, config: Dict[str, Any]):
        self.token = config.get("NOTION_API_TOKEN", "")
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        }
        self.db_faq = config.get("NOTION_DB_FAQ", "")
        self.db_schedule = config.get("NOTION_DB_SCHEDULE", "")
        self.db_homework = config.get("NOTION_DB_HOMEWORK", "")
        self.db_exams = config.get("NOTION_DB_EXAMS", "")
        self.db_leaves = config.get("NOTION_DB_LEAVES", "")
        self.db_line_groups = config.get("NOTION_DB_LINE_GROUPS", "")
        self.db_ai_alerts = config.get("NOTION_DB_AI_ALERTS", "")

        # 快取群組對應班級（減少 API 呼叫）
        self._group_class_cache: Dict[str, Optional[str]] = {}
        self._group_class_name_cache: Dict[str, str] = {}

    # ── FAQ ──────────────────────────────────────────────────────────────────

    def query_faq(self) -> List[Dict[str, Any]]:
        """查詢所有啟用中的 FAQ 條目。"""
        if not self.db_faq:
            logger.warning("NOTION_DB_FAQ not configured")
            return []

        payload = {
            "filter": {
                "property": "啟用",
                "select": {"equals": "啟用"},
            },
            "page_size": 100,
        }
        results = self._query_database(self.db_faq, payload)
        return [self._parse_faq_item(r) for r in results]

    def _parse_faq_item(self, page: Dict) -> Dict[str, Any]:
        props = page.get("properties", {})
        return {
            "question": self._get_title(props, "問題"),
            "answer": self._get_rich_text(props, "回覆"),
            "keywords": self._get_multi_select(props, "關鍵字"),
        }

    # ── 課表 ─────────────────────────────────────────────────────────────────

    def query_schedule(
        self, target_date: date, class_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """查詢指定日期的課表。"""
        if not self.db_schedule:
            logger.warning("NOTION_DB_SCHEDULE not configured")
            return []

        date_str = target_date.isoformat()
        filters: List[Dict] = [
            {"property": "上課日期", "date": {"equals": date_str}},
            {"property": "狀態", "select": {"equals": "正常上課"}},
        ]
        if class_id:
            filters.append(
                {"property": "班級", "relation": {"contains": class_id}}
            )

        payload = {"filter": {"and": filters}, "page_size": 20}
        results = self._query_database(self.db_schedule, payload)
        return [self._parse_schedule_item(r) for r in results]

    def _parse_schedule_item(self, page: Dict) -> Dict[str, Any]:
        props = page.get("properties", {})
        return {
            "class_name": self._get_title(props, "課程名稱"),
            "time_range": self._get_rich_text(props, "上課時間"),
            "room": self._get_rich_text(props, "教室"),
            "note": self._get_rich_text(props, "備注"),
        }

    # ── 作業 ─────────────────────────────────────────────────────────────────

    def query_homework(
        self, due_date: date, class_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """查詢指定截止日的作業。"""
        if not self.db_homework:
            logger.warning("NOTION_DB_HOMEWORK not configured")
            return []

        date_str = due_date.isoformat()
        filters: List[Dict] = [
            {"property": "截止日", "date": {"equals": date_str}},
            {"property": "狀態", "status": {"equals": "已發布"}},
        ]
        if class_id:
            filters.append(
                {"property": "班級", "relation": {"contains": class_id}}
            )

        payload = {"filter": {"and": filters}, "page_size": 20}
        results = self._query_database(self.db_homework, payload)
        return [self._parse_homework_item(r) for r in results]

    def _parse_homework_item(self, page: Dict) -> Dict[str, Any]:
        props = page.get("properties", {})
        return {
            "name": self._get_title(props, "作業名稱"),
            "subject": self._get_select(props, "科目"),
            "content": self._get_rich_text(props, "內容"),
            "note": self._get_rich_text(props, "備注"),
        }

    # ── 考試 ─────────────────────────────────────────────────────────────────

    def query_exams_this_week(
        self, class_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """查詢本週考試。"""
        if not self.db_exams:
            logger.warning("NOTION_DB_EXAMS not configured")
            return []

        today = date.today()
        week_end = today + timedelta(days=7)
        filters: List[Dict] = [
            {"property": "考試日期", "date": {"on_or_after": today.isoformat()}},
            {"property": "考試日期", "date": {"on_or_before": week_end.isoformat()}},
        ]
        if class_id:
            filters.append(
                {"property": "班級", "relation": {"contains": class_id}}
            )

        payload = {
            "filter": {"and": filters},
            "sorts": [{"property": "考試日期", "direction": "ascending"}],
            "page_size": 10,
        }
        results = self._query_database(self.db_exams, payload)
        return [self._parse_exam_item(r) for r in results]

    def _parse_exam_item(self, page: Dict) -> Dict[str, Any]:
        props = page.get("properties", {})
        exam_date_raw = props.get("考試日期", {}).get("date", {})
        exam_date = exam_date_raw.get("start", "") if exam_date_raw else ""
        # 格式化日期 YYYY-MM-DD → MM/DD
        if exam_date and len(exam_date) >= 10:
            exam_date = exam_date[5:10].replace("-", "/")
        return {
            "exam_date": exam_date,
            "subject": self._get_select(props, "科目"),
            "scope": self._get_rich_text(props, "範圍"),
            "note": self._get_rich_text(props, "備注"),
        }

    # ── 請假 ─────────────────────────────────────────────────────────────────

    def create_leave_record(
        self,
        student_name: str,
        leave_date: str,
        reason: str,
        source: str = "LINE",
        user_id_hash: str = "",
    ) -> bool:
        """在 Notion Leaves 資料庫新增請假紀錄。"""
        if not self.db_leaves:
            logger.warning("NOTION_DB_LEAVES not configured")
            return False

        # 解析日期格式 MM/DD → 當年 YYYY-MM-DD
        parsed_date = self._parse_date_string(leave_date)

        payload = {
            "parent": {"database_id": self.db_leaves},
            "properties": {
                "學生姓名": {"title": [{"text": {"content": student_name}}]},
                "請假日期": {"date": {"start": parsed_date}} if parsed_date else {},
                "原因": {"rich_text": [{"text": {"content": reason}}]},
                "登記來源": {"select": {"name": source}},
                "狀態": {"status": {"name": "待確認"}},
                "userId_hash": {"rich_text": [{"text": {"content": user_id_hash}}]},
            },
        }

        try:
            resp = requests.post(
                f"{NOTION_API_BASE}/pages",
                json=payload,
                headers=self._headers,
                timeout=15,
            )
            if resp.status_code not in (200, 201):
                logger.error(
                    "Notion create leave failed: %s %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            return True
        except requests.RequestException as exc:
            logger.exception("Notion create leave error: %s", exc)
            return False

    # ── AI Alerts ────────────────────────────────────────────────────────────

    def create_ai_alert(
        self,
        title: str,
        category: str,
        level: str,
        group_id: str,
        summary: str,
    ) -> bool:
        """在 Notion AI Alerts 資料庫新增風險提醒紀錄。"""
        if not self.db_ai_alerts:
            logger.warning("NOTION_DB_AI_ALERTS not configured")
            return False

        payload = {
            "parent": {"database_id": self.db_ai_alerts},
            "properties": {
                "事件標題": {"title": [{"text": {"content": title}}]},
                "類型": {"select": {"name": category}},
                "等級": {"select": {"name": level}},
                "摘要": {"rich_text": [{"text": {"content": summary[:500]}}]},
                "處理狀態": {"status": {"name": "待處理"}},
            },
        }

        try:
            resp = requests.post(
                f"{NOTION_API_BASE}/pages",
                json=payload,
                headers=self._headers,
                timeout=15,
            )
            return resp.status_code in (200, 201)
        except requests.RequestException as exc:
            logger.exception("Notion create AI alert error: %s", exc)
            return False

    # ── 群組對應班級 ──────────────────────────────────────────────────────────

    def get_class_id_by_group(self, group_id: str) -> Optional[str]:
        """從 LINE Groups 資料庫取得群組對應的班級 ID。"""
        if group_id in self._group_class_cache:
            return self._group_class_cache[group_id]

        if not self.db_line_groups:
            return None

        payload = {
            "filter": {
                "and": [
                    {"property": "LINE groupId", "rich_text": {"equals": group_id}},
                    {"property": "啟用狀態", "select": {"equals": "啟用"}},
                ]
            },
            "page_size": 1,
        }
        results = self._query_database(self.db_line_groups, payload)
        class_id = None
        if results:
            props = results[0].get("properties", {})
            relations = props.get("對應班級", {}).get("relation", [])
            if relations:
                class_id = relations[0].get("id")

        self._group_class_cache[group_id] = class_id
        return class_id

    def get_class_name_by_group(self, group_id: str) -> str:
        """從 LINE Groups 資料庫取得群組對應的班級名稱。"""
        if group_id in self._group_class_name_cache:
            return self._group_class_name_cache[group_id]

        if not self.db_line_groups:
            return "未知班級"

        payload = {
            "filter": {
                "property": "LINE groupId",
                "rich_text": {"equals": group_id},
            },
            "page_size": 1,
        }
        results = self._query_database(self.db_line_groups, payload)
        name = "未知班級"
        if results:
            props = results[0].get("properties", {})
            name = self._get_title(props, "群組名稱") or "未知班級"

        self._group_class_name_cache[group_id] = name
        return name

    # ── 內部工具方法 ──────────────────────────────────────────────────────────

    def _query_database(
        self, database_id: str, payload: Dict
    ) -> List[Dict]:
        """呼叫 Notion Database Query API。"""
        if not database_id or not self.token:
            return []
        try:
            resp = requests.post(
                f"{NOTION_API_BASE}/databases/{database_id}/query",
                json=payload,
                headers=self._headers,
                timeout=15,
            )
            if resp.status_code != 200:
                logger.error(
                    "Notion query failed: db=%s status=%s",
                    database_id[:8],
                    resp.status_code,
                )
                return []
            return resp.json().get("results", [])
        except requests.RequestException as exc:
            logger.exception("Notion query error: %s", exc)
            return []

    @staticmethod
    def _get_title(props: Dict, key: str) -> str:
        items = props.get(key, {}).get("title", [])
        return "".join(i.get("plain_text", "") for i in items)

    @staticmethod
    def _get_rich_text(props: Dict, key: str) -> str:
        items = props.get(key, {}).get("rich_text", [])
        return "".join(i.get("plain_text", "") for i in items)

    @staticmethod
    def _get_select(props: Dict, key: str) -> str:
        sel = props.get(key, {}).get("select")
        return sel.get("name", "") if sel else ""

    @staticmethod
    def _get_multi_select(props: Dict, key: str) -> List[str]:
        items = props.get(key, {}).get("multi_select", [])
        return [i.get("name", "") for i in items]

    @staticmethod
    def _parse_date_string(date_str: str) -> str:
        """將 MM/DD 格式轉換為 YYYY-MM-DD。"""
        import re
        from datetime import date as d

        match = re.match(r"(\d{1,2})[/\-](\d{1,2})", date_str)
        if match:
            month, day = int(match.group(1)), int(match.group(2))
            year = d.today().year
            try:
                return d(year, month, day).isoformat()
            except ValueError:
                pass
        return ""
