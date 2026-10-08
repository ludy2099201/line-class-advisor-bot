"""以補習班所在時區計算「今天」，避免伺服器 UTC 時區造成日期錯置。"""
import logging
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "Asia/Taipei"
# 臺灣無日光節約時間；容器缺少 tz database 時以固定 UTC+8 後備。
_TAIPEI_FIXED_OFFSET = timezone(timedelta(hours=8), DEFAULT_TIMEZONE)


def get_timezone(name: Optional[str] = None) -> tzinfo:
    """取得設定的時區；名稱無效或系統無 tz database 時退回臺灣時間。"""
    tz_name = (name or "").strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Timezone %r unavailable; falling back to UTC+8", tz_name)
        return _TAIPEI_FIXED_OFFSET


def today_local(name: Optional[str] = None, now: Optional[datetime] = None) -> date:
    """回傳指定時區的今天日期；now 僅供測試注入（需含 tzinfo）。"""
    current = now or datetime.now(timezone.utc)
    return current.astimezone(get_timezone(name)).date()
