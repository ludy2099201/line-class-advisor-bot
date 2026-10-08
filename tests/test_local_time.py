"""以補習班時區計算日期的測試。"""
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from app.handlers.schedule_handler import ScheduleHandler
from app.utils.local_time import get_timezone, today_local

# 2026-10-07 23:30 UTC = 2026-10-08 07:30 臺灣時間
EARLY_MORNING_UTC = datetime(2026, 10, 7, 23, 30, tzinfo=timezone.utc)


def test_today_local_uses_taipei_date_before_utc_midnight_rolls_over():
    assert today_local("Asia/Taipei", now=EARLY_MORNING_UTC) == date(2026, 10, 8)


def test_today_local_defaults_to_taipei_when_name_blank():
    assert today_local("", now=EARLY_MORNING_UTC) == date(2026, 10, 8)


def test_invalid_timezone_falls_back_to_utc_plus_8():
    tz = get_timezone("Not/A_Zone")
    assert tz.utcoffset(None).total_seconds() == 8 * 60 * 60
    assert today_local("Not/A_Zone", now=EARLY_MORNING_UTC) == date(2026, 10, 8)


def test_schedule_today_queries_taipei_date():
    notion = MagicMock()
    notion.get_class_id_by_group.return_value = None
    notion.query_schedule.return_value = []
    handler = ScheduleHandler({"GENERIC_TIMEZONE": "Asia/Taipei"}, MagicMock(), notion)

    with patch(
        "app.handlers.schedule_handler.today_local", return_value=date(2026, 10, 8)
    ) as mock_today:
        handler.handle_today({"reply_token": "token", "group_id": None})

    mock_today.assert_called_once_with("Asia/Taipei")
    assert notion.query_schedule.call_args.args[0] == date(2026, 10, 8)
