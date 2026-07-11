# LINE Class Advisor Bot — 補習班 AI 班主任

> 一個部署在 LINE 班級群組的 AI 助理，協助補習班老師維持群組秩序、自動回覆常見問題、查詢課表作業，以及偵測風險訊息。

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.x-green)](https://flask.palletsprojects.com/)
[![Railway](https://img.shields.io/badge/Deploy-Railway-purple)](https://railway.com/)

---

## 功能特色

| 功能 | 說明 |
| :--- | :--- |
| **FAQ 自動回覆** | 從 Notion 資料庫比對關鍵字；無結果時由 LLM 語意搜尋；仍無結果則轉真人 |
| **課表查詢** | 查詢今日／明日課程，依群組對應班級 |
| **作業與考試** | 查詢今日作業與本週考試範圍 |
| **請假引導** | 群組中僅給引導，詳細資料透過私訊收集，保護學生個資 |
| **風險偵測** | LLM JSON mode 分析訊息風險等級（high/medium/low），私下通知管理員，群組中溫和安撫 |

## 設計原則

- **少說話、說對話**：不主動發言，只在被 @AI班主任 或輸入指令時回應
- **不公開個資**：成績、請假原因、繳費狀態一律不在群組揭露
- **不取代真人老師**：超出能力範圍的問題一律引導聯繫真人

---

## 目錄結構

```
line-class-advisor-bot/
├── main.py                    # WSGI 入口（gunicorn main:app）
├── gunicorn.conf.py           # Gunicorn 設定
├── railway.toml               # Railway 部署設定
├── Procfile                   # 啟動指令
├── requirements.txt           # Python 依賴
├── .python-version            # Python 版本（供 Nixpacks 使用）
├── .env.example               # 環境變數範本
├── app/
│   ├── __init__.py            # Flask Application Factory
│   ├── config.py              # 設定類別（從環境變數讀取）
│   ├── routes.py              # LINE Webhook 路由 + 健康檢查
│   ├── handlers/
│   │   ├── router.py          # 訊息路由核心
│   │   ├── faq_handler.py     # FAQ 自動回覆
│   │   ├── schedule_handler.py# 課表查詢
│   │   ├── homework_handler.py# 作業與考試查詢
│   │   ├── leave_handler.py   # 請假引導（多輪對話）
│   │   └── risk_handler.py    # 風險偵測與通知
│   ├── services/
│   │   ├── line_api.py        # LINE Messaging API 封裝
│   │   ├── notion_service.py  # Notion API 封裝
│   │   └── llm_service.py     # OpenAI LLM 封裝（含 JSON mode）
│   └── utils/
│       └── session_store.py   # Session 管理（Redis / In-Memory 自動切換）
└── tests/
    ├── test_router.py
    ├── test_notion_service.py
    └── test_session_store.py
```

---

## 快速開始（本地開發）

### 1. 複製環境變數範本

```bash
cp .env.example .env
# 編輯 .env 填入實際值
```

### 2. 安裝依賴

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 啟動開發伺服器

```bash
python main.py
# 或使用 gunicorn
gunicorn main:app --config gunicorn.conf.py
```

### 4. 設定 LINE Webhook

使用 [ngrok](https://ngrok.com/) 建立公開 URL：

```bash
ngrok http 5000
```

在 LINE Developers Console 將 Webhook URL 設為：
```
https://<your-ngrok-url>/linebot
```

---

## 部署到 Railway

### 步驟

1. Fork 此專案到您的 GitHub
2. 在 [Railway](https://railway.com/) 建立新專案，選擇「Deploy from GitHub repo」
3. 在 **Variables** 頁面設定所有環境變數（參考 `.env.example`）
4. （建議）加入 **Redis Plugin**：點選 **+ New** → **Database** → **Add Redis**

Railway 會自動注入 `REDIS_URL`，Session 管理器將自動切換至 Redis 模式以支援多實例部署。

### 必要環境變數

| 變數名稱 | 說明 |
| :--- | :--- |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Channel Access Token |
| `LINE_CHANNEL_SECRET` | LINE Channel Secret |
| `NOTION_API_TOKEN` | Notion Integration Token |
| `NOTION_DB_FAQ` | FAQ 資料庫 ID |
| `NOTION_DB_SCHEDULE` | 課表資料庫 ID |
| `NOTION_DB_HOMEWORK` | 作業資料庫 ID |
| `NOTION_DB_LEAVES` | 請假資料庫 ID |
| `NOTION_DB_AI_ALERTS` | AI 警報資料庫 ID |
| `OPENAI_API_KEY` | OpenAI API Key |
| `ADMIN_LINE_USER_ID` | 管理員 LINE User ID（接收風險通知）|
| `CRAM_SCHOOL_NAME` | 補習班名稱 |
| `BOT_NAME` | Bot 顯示名稱 |

### 健康檢查

Railway 會定期呼叫 `GET /health`，回應範例：

```json
{
  "status": "ok",
  "bot": "AI班主任",
  "school": "Moosie 補習班",
  "missing_config": []
}
```

若有必要環境變數未設定，`status` 會顯示 `"degraded"` 並列出缺少的變數名稱，方便快速診斷部署問題。

---

## 技術架構

```
LINE Platform
    │ Webhook POST /linebot
    ▼
Flask (routes.py)
    │ 驗證簽章 → 解析事件 → 精確錯誤處理
    ▼
LineRouter (handlers/router.py)
    │ 判斷群組/私訊、指令類型
    ├─→ FaqHandler      → LLM.chat() + Notion FAQ DB
    ├─→ ScheduleHandler → Notion Schedule DB
    ├─→ HomeworkHandler → Notion Homework DB
    ├─→ LeaveHandler    → SessionStore (Redis/Memory) + Notion Leaves DB
    └─→ RiskHandler     → LLM.chat_json() [JSON mode] + Notion AI Alerts DB
                                              │
                                              └─→ LINE Push (Admin 通知)
```

### Session 管理策略

`SessionStore` 支援雙後端自動切換：

- **有 `REDIS_URL`**：使用 Redis，支援多實例部署，TTL 自動管理
- **無 `REDIS_URL`**：退回 In-Memory，適合本地開發與單實例部署
- **Redis 故障時**：自動 fallback 至 In-Memory，確保服務不中斷

---

## Notion 資料庫設定

請建立以下資料庫並授予 Integration 存取權限：

| 資料庫 | 必要欄位 |
| :--- | :--- |
| FAQ | 問題 (Title)、回覆 (Rich Text)、關鍵字 (Multi-select)、啟用 (Select) |
| Schedule | 課程名稱 (Title)、上課日期 (Date)、班級 (Relation) |
| Homework | 作業名稱 (Title)、截止日 (Date)、科目 (Select)、班級 (Relation) |
| Leaves | 學生姓名 (Title)、請假日期 (Date)、原因 (Rich Text)、狀態 (Status) |
| LINE Groups | 群組名稱 (Title)、LINE groupId (Rich Text)、對應班級 (Relation) |
| AI Alerts | 事件標題 (Title)、類型 (Select)、等級 (Select)、摘要 (Rich Text) |

---

## 授權

MIT License
