#!/usr/bin/env python3
"""驗證直接依賴的 Notion 資料庫 schema；不建立或修改任何 Notion 資料。"""
import os
import sys
from typing import Dict, Iterable, Tuple

import requests

API_BASE = "https://api.notion.com/v1"
API_VERSION = "2022-06-28"

# (environment variable, label, required property name -> allowed Notion types)
CONTRACTS: Iterable[Tuple[str, str, Dict[str, set[str]]]] = (
    (
        "NOTION_DB_FAQ",
        "FAQ",
        {"啟用": {"checkbox"}, "問題": {"title"}, "答案": {"rich_text"}, "關鍵字": {"rich_text", "multi_select"}},
    ),
    (
        "NOTION_DB_CLASSES",
        "Classes",
        {"開課中": {"checkbox"}, "班名": {"title"}, "時段": {"rich_text"}, "上課週幾": {"multi_select"}},
    ),
    (
        "NOTION_DB_LINE_GROUPS",
        "LINE Groups",
        {"群組名稱": {"title"}, "LINE groupId": {"rich_text"}, "對應班級": {"rich_text"}, "啟用狀態": {"select"}},
    ),
)


def main() -> int:
    token = os.environ.get("NOTION_API_TOKEN", "")
    if not token:
        print("schema_check status=failed reason=NOTION_API_TOKEN_missing")
        return 2

    headers = {"Authorization": f"Bearer {token}", "Notion-Version": API_VERSION}
    failures = []
    for env_name, label, properties in CONTRACTS:
        database_id = os.environ.get(env_name, "")
        if not database_id:
            failures.append(f"{label}:config_missing:{env_name}")
            continue
        try:
            response = requests.get(
                f"{API_BASE}/databases/{database_id}", headers=headers, timeout=15
            )
        except requests.RequestException:
            failures.append(f"{label}:metadata_unavailable")
            continue
        if response.status_code != 200:
            failures.append(f"{label}:metadata_unavailable:status_{response.status_code}")
            continue
        payload = response.json()
        actual = payload.get("properties", {})
        for property_name, allowed_types in properties.items():
            item = actual.get(property_name)
            if not item:
                failures.append(f"{label}:property_missing:{property_name}")
            elif item.get("type") not in allowed_types:
                allowed = "/".join(sorted(allowed_types))
                failures.append(f"{label}:type_mismatch:{property_name}:expected_{allowed}:actual_{item.get('type')}")

    if failures:
        for failure in failures:
            print(f"schema_check status=failed reason={failure}")
        return 1
    print("schema_check status=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
