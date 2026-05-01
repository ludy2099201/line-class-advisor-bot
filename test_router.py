"""
Router 單元測試
測試訊息解析、指令辨識、靜默規則與個資保護邏輯。
"""
import pytest
from unittest.mock import MagicMock, patch

from app.handlers.router import LineRouter

MOCK_CONFIG = {
    "LINE_CHANNEL_ACCESS_TOKEN": "test_token",
    "LINE_CHANNEL_SECRET": "test_secret",
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
    "OPENAI_API_KEY": "",
    "LLM_MODEL": "gpt-4.1-mini",
    "ADMIN_LINE_USER_ID": "U_admin",
    "CRAM_SCHOOL_NAME": "測試補習班",
    "BOT_NAME": "AI班主任",
}


def make_text_event(
    text: str,
    source_type: str = "group",
    user_id: str = "U123",
    group_id: str = "C456",
    reply_token: str = "reply_token_abc",
) -> dict:
    event = {
        "type": "message",
        "replyToken": reply_token,
        "source": {"type": source_type, "userId": user_id},
        "message": {"type": "text", "text": text},
    }
    if source_type == "group":
        event["source"]["groupId"] = group_id
    return event


@pytest.fixture
def router():
    with patch("app.handlers.router.LineApiService"), \
         patch("app.handlers.router.NotionService"), \
         patch("app.handlers.router.FaqHandler"), \
         patch("app.handlers.router.ScheduleHandler"), \
         patch("app.handlers.router.HomeworkHandler"), \
         patch("app.handlers.router.LeaveHandler"), \
         patch("app.handlers.router.RiskHandler"):
        r = LineRouter(MOCK_CONFIG)
        return r


class TestContextParsing:
    """測試 _parse_context 的解析邏輯。"""

    def test_mentioned_in_group(self, router):
        ctx = router._parse_context(
            text="@AI班主任 今日課表",
            source_type="group",
            user_id="U1",
            group_id="G1",
            reply_token="r1",
        )
        assert ctx["is_mentioned"] is True
        assert ctx["command"] == "schedule_today"
        assert ctx["should_reply"] is True

    def test_command_without_mention(self, router):
        ctx = router._parse_context(
            text="今日作業",
            source_type="group",
            user_id="U1",
            group_id="G1",
            reply_token="r1",
        )
        assert ctx["is_command"] is True
        assert ctx["command"] == "homework_today"
        assert ctx["should_reply"] is True

    def test_general_chat_is_silent(self, router):
        ctx = router._parse_context(
            text="今天天氣真好",
            source_type="group",
            user_id="U1",
            group_id="G1",
            reply_token="r1",
        )
        assert ctx["should_reply"] is False
        assert ctx["is_command"] is False
        assert ctx["is_mentioned"] is False

    def test_privacy_keyword_detected(self, router):
        ctx = router._parse_context(
            text="@AI班主任 我的成績怎麼樣",
            source_type="group",
            user_id="U1",
            group_id="G1",
            reply_token="r1",
        )
        assert ctx["is_privacy_candidate"] is True

    def test_risk_keyword_detected(self, router):
        ctx = router._parse_context(
            text="我真的不想活了",
            source_type="group",
            user_id="U1",
            group_id="G1",
            reply_token="r1",
        )
        assert ctx["is_risk_candidate"] is True

    def test_dm_always_replies(self, router):
        ctx = router._parse_context(
            text="你好",
            source_type="user",
            user_id="U1",
            group_id=None,
            reply_token="r1",
        )
        assert ctx["should_reply"] is True

    def test_exam_command(self, router):
        ctx = router._parse_context(
            text="考試範圍",
            source_type="group",
            user_id="U1",
            group_id="G1",
            reply_token="r1",
        )
        assert ctx["command"] == "exam_query"

    def test_leave_command(self, router):
        ctx = router._parse_context(
            text="請假",
            source_type="group",
            user_id="U1",
            group_id="G1",
            reply_token="r1",
        )
        assert ctx["command"] == "leave"


class TestPrivacyProtection:
    """測試群組個資保護邏輯。"""

    def test_privacy_reply_in_group(self, router):
        event = make_text_event("@AI班主任 我的學費繳了嗎")
        router.line_api.reply = MagicMock()
        router._handle_text_event(event)
        # 應該回覆個資保護訊息
        router.line_api.reply.assert_called_once()
        call_args = router.line_api.reply.call_args[0]
        assert "個人資料" in call_args[1] or "個資" in call_args[1]


class TestSilentRule:
    """測試靜默規則。"""

    def test_general_chat_no_reply(self, router):
        event = make_text_event("今天午餐吃什麼")
        router.line_api.reply = MagicMock()
        router._handle_text_event(event)
        router.line_api.reply.assert_not_called()
