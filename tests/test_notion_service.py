"""
Notion Service 單元測試
測試資料解析與日期轉換邏輯。
"""
import pytest
from app.services.notion_service import NotionService

MOCK_CONFIG = {
    "NOTION_API_TOKEN": "",
    "NOTION_DB_FAQ": "",
    "NOTION_DB_SCHEDULE": "",
    "NOTION_DB_HOMEWORK": "",
    "NOTION_DB_EXAMS": "",
    "NOTION_DB_LEAVES": "",
    "NOTION_DB_LINE_GROUPS": "",
    "NOTION_DB_AI_ALERTS": "",
    "NOTION_DB_STAFF": "",
    "NOTION_DB_CLASSES": "",
}


@pytest.fixture
def notion():
    return NotionService(MOCK_CONFIG)


class TestDateParsing:
    def test_parse_mm_dd_slash(self, notion):
        result = NotionService._parse_date_string("05/10")
        assert result.endswith("-05-10")

    def test_parse_mm_dd_hyphen(self, notion):
        result = NotionService._parse_date_string("5-10")
        assert result.endswith("-05-10")

    def test_parse_invalid(self, notion):
        result = NotionService._parse_date_string("invalid")
        assert result == ""


class TestPropertyParsers:
    def test_get_title(self, notion):
        props = {
            "問題": {
                "title": [{"plain_text": "學費怎麼繳？"}]
            }
        }
        assert NotionService._get_title(props, "問題") == "學費怎麼繳？"

    def test_get_rich_text(self, notion):
        props = {
            "回覆": {
                "rich_text": [{"plain_text": "可以用轉帳或現金繳費。"}]
            }
        }
        assert NotionService._get_rich_text(props, "回覆") == "可以用轉帳或現金繳費。"

    def test_get_select(self, notion):
        props = {
            "科目": {"select": {"name": "數學"}}
        }
        assert NotionService._get_select(props, "科目") == "數學"

    def test_get_multi_select(self, notion):
        props = {
            "關鍵字": {
                "multi_select": [{"name": "學費"}, {"name": "繳費"}]
            }
        }
        result = NotionService._get_multi_select(props, "關鍵字")
        assert "學費" in result
        assert "繳費" in result
