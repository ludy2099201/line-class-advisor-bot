"""
Notion API 服務封裝
提供查詢 FAQ、課表、作業、考試、請假、群組對應等功能。

欄位對應（以 Notion 資料庫實際欄位名稱為準）：
  FAQ:      問題(title) | 答案(rich_text) | 關鍵字(multi_select) | 啟用(checkbox) | 分類(select)
  課表:     課程標題(title) | 上課時段(date) | 課程主題(rich_text) | 教室(rich_text) | 備註(rich_text) | 狀態(status)
  作業:     作業名稱(title) | 科目(select) | 截止日(date) | 內容(rich_text) | 班級(rich_text) | 狀態(status)
  考試:     考試名稱(title) | 科目(select) | 考試日期(date) | 範圍(rich_text) | 班級(rich_text)
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
        self.db_classes = config.get("NOTION_DB_CLASSES", "")
        self.db_notes = config.get("NOTION_DB_NOTES", "")

        # 快取群組對應班級（減少 API 呼叫）
        self._group_class_cache: Dict[str, Optional[str]] = {}
        self._group_class_name_cache: Dict[str, str] = {}

    # ── FAQ ──────────────────────────────────────────────────────────────────

    def query_faq(self) -> List[Dict[str, Any]]:
        """查詢所有啟用中的 FAQ 條目。
        
        Notion 欄位：啟用(checkbox) | 問題(title) | 答案(rich_text) | 關鍵字(multi_select)
        """
        if not self.db_faq:
            logger.warning("NOTION_DB_FAQ not configured")
            return []

        payload = {
            "filter": {
                "property": "啟用",
                "checkbox": {"equals": True},
            },
            "page_size": 100,
        }
        results = self._query_database(self.db_faq, payload)
        parsed = [self._parse_faq_item(r) for r in results]
        logger.info("FAQ query returned %d items", len(parsed))
        return parsed

    def _parse_faq_item(self, page: Dict) -> Dict[str, Any]:
        props = page.get("properties", {})
        # 關鍵字欄位為逗號分隔的 rich_text（e.g. "老師,師資,教學經驗"）
        keywords_raw = self._get_rich_text(props, "關鍵字")
        keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()] if keywords_raw else []
        # 也嘗試 multi_select 格式（相容兩種設計）
        if not keywords:
            keywords = self._get_multi_select(props, "關鍵字")
        return {
            "question": self._get_title(props, "問題"),
            "answer": self._get_rich_text(props, "答案"),
            "keywords": keywords,
        }

    # ── 課表 ─────────────────────────────────────────────────────────────────

    def query_schedule(
        self, target_date: date, class_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """查詢指定日期的課表。
        
        Notion 欄位：課程標題(title) | 上課時段(date) | 課程主題(rich_text) | 教室(rich_text) | 備註(rich_text)
        class_id 實際上是班級名稱字串（從 LINE Groups 資料庫取得），用於篩選課程標題。
        """
        if not self.db_schedule:
            logger.warning("NOTION_DB_SCHEDULE not configured")
            return []

        date_str = target_date.isoformat()
        # 課表的「上課時段」是含時間的 date 欄位，需用 on_or_after + before 範圍查詢
        next_date_str = (target_date + timedelta(days=1)).isoformat()
        filters: List[Dict] = [
            {"property": "上課時段", "date": {"on_or_after": date_str}},
            {"property": "上課時段", "date": {"before": next_date_str}},
        ]

        # 若有班級名稱，加入課程標題篩選
        if class_id:
            filters.append(
                {"property": "課程標題", "title": {"contains": class_id}}
            )
            logger.info("Schedule query with class filter: %s", class_id)

        payload = {
            "filter": {"and": filters},
            "sorts": [{"property": "上課時段", "direction": "ascending"}],
            "page_size": 20,
        }
        results = self._query_database(self.db_schedule, payload)
        parsed = [self._parse_schedule_item(r) for r in results]
        logger.info("Schedule query for %s (class=%s) returned %d items", date_str, class_id, len(parsed))
        return parsed

    def _parse_schedule_item(self, page: Dict) -> Dict[str, Any]:
        props = page.get("properties", {})
        # 解析 date 欄位（上課時段）
        date_prop = props.get("上課時段", {}).get("date") or {}
        start = date_prop.get("start", "")
        end = date_prop.get("end", "")
        # 格式化時間段（只取時間部分 HH:MM）
        time_range = ""
        if start:
            time_range = start[11:16] if len(start) > 10 else start
        if end:
            time_range += f"–{end[11:16]}" if len(end) > 10 else f"–{end}"

        return {
            "class_name": self._get_title(props, "課程標題"),
            "subject": self._get_rich_text(props, "課程主題"),
            "time_range": time_range,
            "room": self._get_rich_text(props, "教室"),
            "note": self._get_rich_text(props, "備註"),
        }

    # ── 作業 ─────────────────────────────────────────────────────────────────

    def query_homework(
        self, due_date: date, class_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """查詢指定截止日的作業。
        
        Notion 欄位：作業名稱(title) | 科目(select) | 截止日(date) | 內容(rich_text) | 班級(rich_text) | 狀態(status)
        class_id 實際上是班級名稱字串，用於篩選「班級」欄位。
        """
        if not self.db_homework:
            logger.warning("NOTION_DB_HOMEWORK not configured")
            return []

        date_str = due_date.isoformat()
        filters: List[Dict] = [
            {"property": "截止日", "date": {"equals": date_str}},
        ]

        # 若有班級名稱，加入班級欄位篩選
        if class_id:
            filters.append(
                {"property": "班級", "rich_text": {"contains": class_id}}
            )
            logger.info("Homework query with class filter: %s", class_id)

        payload = {"filter": {"and": filters}, "page_size": 20}
        results = self._query_database(self.db_homework, payload)
        parsed = [self._parse_homework_item(r) for r in results]
        logger.info("Homework query for %s (class=%s) returned %d items", date_str, class_id, len(parsed))
        return parsed

    def _parse_homework_item(self, page: Dict) -> Dict[str, Any]:
        props = page.get("properties", {})
        return {
            "name": self._get_title(props, "作業名稱"),
            "subject": self._get_select(props, "科目"),
            "content": self._get_rich_text(props, "內容"),
            "class_name": self._get_rich_text(props, "班級"),
            "note": "",
        }

    # ── 考試 ─────────────────────────────────────────────────────────────────

    def query_exams_this_week(
        self, class_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """查詢未來 14 天內的考試（擴大範圍確保有資料）。
        
        Notion 欄位：考試名稱(title) | 科目(select) | 考試日期(date) | 範圍(rich_text) | 班級(rich_text)
        """
        if not self.db_exams:
            logger.warning("NOTION_DB_EXAMS not configured")
            return []

        today = date.today()
        week_end = today + timedelta(days=14)
        filters: List[Dict] = [
            {"property": "考試日期", "date": {"on_or_after": today.isoformat()}},
            {"property": "考試日期", "date": {"on_or_before": week_end.isoformat()}},
        ]

        payload = {
            "filter": {"and": filters},
            "sorts": [{"property": "考試日期", "direction": "ascending"}],
            "page_size": 10,
        }
        results = self._query_database(self.db_exams, payload)
        parsed = [self._parse_exam_item(r) for r in results]
        logger.info("Exam query returned %d items", len(parsed))
        return parsed

    def _parse_exam_item(self, page: Dict) -> Dict[str, Any]:
        props = page.get("properties", {})
        exam_date_raw = props.get("考試日期", {}).get("date") or {}
        exam_date = exam_date_raw.get("start", "")
        # 格式化日期 YYYY-MM-DD → MM/DD（週幾）
        if exam_date and len(exam_date) >= 10:
            from datetime import datetime
            try:
                dt = datetime.strptime(exam_date[:10], "%Y-%m-%d")
                weekdays = ["一", "二", "三", "四", "五", "六", "日"]
                exam_date = f"{exam_date[5:10].replace('-', '/')}（週{weekdays[dt.weekday()]}）"
            except ValueError:
                exam_date = exam_date[5:10].replace("-", "/")
        return {
            "exam_name": self._get_title(props, "考試名稱"),
            "exam_date": exam_date,
            "subject": self._get_select(props, "科目"),
            "scope": self._get_rich_text(props, "範圍"),
            "class_name": self._get_rich_text(props, "班級"),
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
        """從 LINE Groups 資料庫取得群組對應的班級名稱（作為 class_id 使用）。
        
        Notion 欄位：LINE groupId(rich_text) | 對應班級(rich_text) | 啟用狀態(select)
        回傳班級名稱字串，供課表/作業查詢篩選使用；找不到時回傳 None。
        """
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
        class_name = None
        if results:
            props = results[0].get("properties", {})
            # 對應班級是 rich_text 欄位，存班級名稱文字
            class_name = self._get_rich_text(props, "對應班級") or None

        self._group_class_cache[group_id] = class_name
        logger.info("Group %s mapped to class: %s", group_id[:8], class_name)
        return class_name

    def get_class_name_by_group(self, group_id: str) -> str:
        """從 LINE Groups 資料庫取得群組名稱（顯示用）。"""
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

    def list_classes(self) -> List[Dict[str, Any]]:
        """列出所有開課中的班級，供綁定流程顯示選單。"""
        if not self.db_classes:
            logger.warning("NOTION_DB_CLASSES not configured")
            return []

        payload = {
            "filter": {"property": "開課中", "checkbox": {"equals": True}},
            "sorts": [{"property": "班名", "direction": "ascending"}],
            "page_size": 50,
        }
        results = self._query_database(self.db_classes, payload)
        classes = []
        for row in results:
            props = row.get("properties", {})
            name = self._get_title(props, "班名")
            time_slot = self._get_rich_text(props, "時段")
            days = self._get_multi_select(props, "上課週幾")
            if name:
                classes.append({
                    "name": name,
                    "time_slot": time_slot,
                    "days": "、".join(days) if days else "",
                })
        logger.info("list_classes returned %d items", len(classes))
        return classes

    def bind_group_to_class(
        self, group_id: str, group_name: str, class_name: str
    ) -> bool:
        """將 LINE groupId 寫入 LINE Groups 資料庫，完成群組綁定。
        
        若已有同名群組記錄則更新，否則新增。
        """
        if not self.db_line_groups:
            logger.warning("NOTION_DB_LINE_GROUPS not configured")
            return False

        # 先查詢是否已有此 groupId 的記錄
        payload = {
            "filter": {
                "property": "LINE groupId",
                "rich_text": {"equals": group_id},
            },
            "page_size": 1,
        }
        existing = self._query_database(self.db_line_groups, payload)

        properties = {
            "群組名稱": {"title": [{"text": {"content": group_name}}]},
            "LINE groupId": {"rich_text": [{"text": {"content": group_id}}]},
            "對應班級": {"rich_text": [{"text": {"content": class_name}}]},
            "啟用狀態": {"select": {"name": "啟用"}},
        }

        try:
            if existing:
                # 更新現有記錄
                page_id = existing[0]["id"]
                resp = requests.patch(
                    f"{NOTION_API_BASE}/pages/{page_id}",
                    json={"properties": properties},
                    headers=self._headers,
                    timeout=15,
                )
            else:
                # 新增記錄
                resp = requests.post(
                    f"{NOTION_API_BASE}/pages",
                    json={"parent": {"database_id": self.db_line_groups}, "properties": properties},
                    headers=self._headers,
                    timeout=15,
                )
            if resp.status_code in (200, 201):
                # 清除快取，讓下次查詢取得最新資料
                self._group_class_cache.pop(group_id, None)
                self._group_class_name_cache.pop(group_id, None)
                logger.info("Group %s bound to class %s", group_id[:8], class_name)
                return True
            logger.error("bind_group_to_class failed: %s %s", resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as exc:
            logger.exception("bind_group_to_class error: %s", exc)
            return False

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
                    "Notion query failed: db=%s status=%s body=%s",
                    database_id[:8],
                    resp.status_code,
                    resp.text[:300],
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


    # ── 課後筆記 Notes ────────────────────────────────────────────────────────

    def create_note(
        self,
        title: str,
        student: str,
        date: str,
        course: str = "",
        teacher: str = "",
        performance: str = "",
        emotion: str = "",
        content: str = "",
        followup: str = "",
        recorder_user_id: str = ""
    ) -> bool:
        """新增一筆課後筆記到 Notion。"""
        if not self.db_notes:
            logger.warning("NOTION_DB_NOTES 未設定，無法儲存課後筆記")
            return False

        properties: Dict[str, Any] = {
            "筆記標題": {"title": [{"text": {"content": title}}]},
            "學生姓名": {"rich_text": [{"text": {"content": student}}]},
            "記錄日期": {"date": {"start": date}},
        }
        if course:
            properties["課程"] = {"rich_text": [{"text": {"content": course}}]}
        if teacher:
            properties["老師"] = {"rich_text": [{"text": {"content": teacher}}]}
        if performance:
            properties["學習表現"] = {"select": {"name": performance}}
        if emotion:
            properties["情緒狀態"] = {"select": {"name": emotion}}
        if content:
            properties["筆記內容"] = {"rich_text": [{"text": {"content": content[:2000]}}]}
        if followup:
            properties["追蹤事項"] = {"rich_text": [{"text": {"content": followup[:2000]}}]}
        if recorder_user_id:
            properties["LINE 記錄者 userId"] = {"rich_text": [{"text": {"content": recorder_user_id}}]}

        payload = {
            "parent": {"database_id": self.db_notes},
            "properties": properties
        }
        try:
            r = requests.post(f"{NOTION_API_BASE}/pages", headers=self._headers, json=payload, timeout=10)
            if r.status_code not in (200, 201):
                logger.error(f"新增課後筆記失敗: {r.status_code} {r.text[:200]}")
                return False
            return True
        except Exception as e:
            logger.error(f"新增課後筆記例外: {e}")
            return False

    def get_student_notes(self, student_name: str, limit: int = 5) -> List[Dict[str, Any]]:
        """查詢特定學生的歷史課後筆記（最新在前）。"""
        if not self.db_notes:
            return []

        payload = {
            "filter": {
                "property": "學生姓名",
                "rich_text": {"contains": student_name}
            },
            "sorts": [{"property": "記錄日期", "direction": "descending"}],
            "page_size": limit
        }
        try:
            r = requests.post(
                f"{NOTION_API_BASE}/databases/{self.db_notes}/query",
                headers=self._headers, json=payload, timeout=10
            )
            if r.status_code != 200:
                logger.error(f"查詢學生筆記失敗: {r.status_code}")
                return []

            results = []
            for page in r.json().get("results", []):
                props = page["properties"]
                date_val = props.get("記錄日期", {}).get("date")
                results.append({
                    "student": self._get_rich_text(props, "學生姓名"),
                    "date": date_val.get("start", "") if date_val else "",
                    "course": self._get_rich_text(props, "課程"),
                    "teacher": self._get_rich_text(props, "老師"),
                    "performance": self._get_select(props, "學習表現"),
                    "emotion": self._get_select(props, "情緒狀態"),
                    "content": self._get_rich_text(props, "筆記內容"),
                    "followup": self._get_rich_text(props, "追蹤事項"),
                })
            return results
        except Exception as e:
            logger.error(f"查詢學生筆記例外: {e}")
            return []

    def get_notes_by_date(self, date_str: str) -> List[Dict[str, Any]]:
        """查詢特定日期的所有課後筆記。"""
        if not self.db_notes:
            return []

        payload = {
            "filter": {
                "and": [
                    {"property": "記錄日期", "date": {"on_or_after": date_str}},
                    {"property": "記錄日期", "date": {"on_or_before": date_str}}
                ]
            },
            "sorts": [{"property": "記錄日期", "direction": "ascending"}],
            "page_size": 50
        }
        try:
            r = requests.post(
                f"{NOTION_API_BASE}/databases/{self.db_notes}/query",
                headers=self._headers, json=payload, timeout=10
            )
            if r.status_code != 200:
                return []

            results = []
            for page in r.json().get("results", []):
                props = page["properties"]
                results.append({
                    "student": self._get_rich_text(props, "學生姓名"),
                    "course": self._get_rich_text(props, "課程"),
                    "teacher": self._get_rich_text(props, "老師"),
                    "performance": self._get_select(props, "學習表現"),
                    "emotion": self._get_select(props, "情緒狀態"),
                    "content": self._get_rich_text(props, "筆記內容"),
                    "followup": self._get_rich_text(props, "追蹤事項"),
                })
            return results
        except Exception as e:
            logger.error(f"查詢日期筆記例外: {e}")
            return []
