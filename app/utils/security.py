"""存取控制、審計與最小化資料遮罩工具。"""
import hashlib
import logging
import re
from typing import Iterable, Set

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_TW_MOBILE_RE = re.compile(r"(?<!\d)(?:\+?886[-\s]?)?0?9\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)")
_TW_ID_RE = re.compile(r"\b[A-Z][12]\d{8}\b", re.IGNORECASE)


def parse_user_ids(value: str) -> Set[str]:
    """將逗號分隔的 LINE user ID 設定轉為集合。"""
    return {item.strip() for item in (value or "").split(",") if item.strip()}


def short_hash(value: str) -> str:
    """回傳不可逆的短雜湊，供 log 關聯而不暴露識別碼。"""
    if not value:
        return "-"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def audit_event(action: str, outcome: str, actor_id: str = "", group_id: str = "") -> None:
    """記錄不含原始訊息與明文識別碼的安全審計事件。"""
    logger.info(
        "audit_event action=%s outcome=%s actor=%s group=%s",
        action,
        outcome,
        short_hash(actor_id),
        short_hash(group_id),
    )


def redact_direct_identifiers(text: str) -> str:
    """遮罩常見 email、臺灣手機與身分證字號；非完整 DLP 替代方案。"""
    redacted = _EMAIL_RE.sub("[EMAIL_REDACTED]", text or "")
    redacted = _TW_MOBILE_RE.sub("[PHONE_REDACTED]", redacted)
    return _TW_ID_RE.sub("[NATIONAL_ID_REDACTED]", redacted)


def is_allowed(user_id: str, allowlist: Iterable[str]) -> bool:
    """以明確 allowlist 判斷使用者是否可進行敏感操作。"""
    return bool(user_id) and user_id in set(allowlist)
