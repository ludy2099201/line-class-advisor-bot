# LINE Class Advisor Bot — 補習班 AI 班主任

這是一個專為補習班 LINE 班級群組設計的「AI 班主任」機器人。
核心原則：**少說話、說對話；不公開個資、不取代真人老師；先做可驗證 MVP，再逐步擴充。**

## 專案定位

AI 班主任不是客服機器人，而是放在班級 LINE 群組裡的秩序維護、提醒、查詢與風險分流助理。

### 核心功能 (MVP)

1. **單一 LINE Webhook Router**：所有訊息進入同一個入口，再依規則分流。
2. **身份與群組辨識**：辨識老師、行政、家長、學生與班級群組。
3. **FAQ 自動回覆**：回答學費、請假、補課、上課時間等常見問題。
4. **課表查詢**：從 Notion 課表資料庫回覆今日／明日課程資訊。
5. **作業與考試提醒**：查詢今日／明日作業、本週考試範圍。
6. **請假引導**：群組內簡短引導，詳細資料轉私訊收集，避免個資外洩。
7. **風險訊息提醒**：偵測客訴、霸凌、自傷、個資外洩等訊號，私下通知老師／行政。

## 系統架構

- **前端介面**：LINE Messaging API
- **後端服務**：Python Flask (Gunicorn)
- **資料庫**：Notion API (FAQ, 課表, 作業, 考試, 請假, 群組, 風險提醒)
- **AI 引擎**：OpenAI API (GPT-4.1-mini) 用於 FAQ 語意比對與風險分析
- **部署環境**：Railway (Nixpacks)

## 專案結構

```text
line-class-advisor-bot/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── config.py            # 環境變數設定
│   ├── routes.py            # LINE Webhook 路由
│   ├── handlers/            # 業務邏輯處理器
│   │   ├── router.py        # 訊息分流核心
│   │   ├── faq_handler.py   # FAQ 回覆
│   │   ├── schedule_handler.py # 課表查詢
│   │   ├── homework_handler.py # 作業/考試查詢
│   │   ├── leave_handler.py # 請假引導
│   │   └── risk_handler.py  # 風險偵測
│   ├── services/            # 外部 API 服務封裝
│   │   ├── line_api.py      # LINE Messaging API
│   │   ├── notion_service.py # Notion API
│   │   └── llm_service.py   # OpenAI API
│   └── utils/
│       └── session_store.py # 簡易 In-Memory Session (請假多輪對話)
├── tests/                   # 單元測試
├── main.py                  # 應用程式入口
├── requirements.txt         # Python 依賴套件
├── .env.example             # 環境變數範本
├── Procfile                 # Railway 啟動指令
└── railway.toml             # Railway 部署設定
```

## 本地開發與測試

### 1. 環境準備

```bash
# 建立虛擬環境
python -m venv venv
source venv/bin/activate

# 安裝依賴套件
pip install -r requirements.txt
```

### 2. 設定環境變數

複製 `.env.example` 為 `.env`，並填入您的 API 金鑰與 Notion 資料庫 ID：

```bash
cp .env.example .env
```

### 3. 執行測試

```bash
pytest tests/ -v
```

### 4. 啟動服務

```bash
python main.py
```

服務將在 `http://localhost:5000` 啟動。您可以使用 ngrok 將本地 port 暴露到外網，以供 LINE Webhook 測試：

```bash
ngrok http 5000
```

將 ngrok 產生的 HTTPS URL 加上 `/linebot` 路徑（例如 `https://xxxx.ngrok.io/linebot`）填入 LINE Developers Console 的 Webhook URL。

## 部署至 Railway

本專案已包含 `Procfile` 與 `railway.toml`，可直接部署至 Railway。

1. 在 Railway 建立新專案，選擇 "Deploy from GitHub repo"。
2. 選擇本專案的 repository。
3. 在 Railway 的 Variables 設定頁面，填入 `.env.example` 中的所有環境變數。
4. 部署完成後，將 Railway 提供的 Public Domain 加上 `/linebot` 路徑，填入 LINE Developers Console 的 Webhook URL。

## Notion 資料庫設定指南

請參考規格書建立以下 Notion 資料庫，並將其 ID 填入環境變數：

1. **FAQ**：包含「問題」(Title)、「回覆」(Rich Text)、「關鍵字」(Multi-select)、「啟用」(Select)。
2. **Schedule (課表)**：包含「課程名稱」(Title)、「上課日期」(Date)、「上課時間」(Rich Text)、「教室」(Rich Text)、「狀態」(Select)、「班級」(Relation)。
3. **Homework (作業)**：包含「作業名稱」(Title)、「截止日」(Date)、「科目」(Select)、「內容」(Rich Text)、「狀態」(Status)、「班級」(Relation)。
4. **Exams (考試)**：包含「考試名稱」(Title)、「考試日期」(Date)、「科目」(Select)、「範圍」(Rich Text)、「班級」(Relation)。
5. **Leaves (請假)**：包含「學生姓名」(Title)、「請假日期」(Date)、「原因」(Rich Text)、「狀態」(Status)、「登記來源」(Select)。
6. **LINE Groups (群組)**：包含「群組名稱」(Title)、「LINE groupId」(Rich Text)、「對應班級」(Relation)、「啟用狀態」(Select)。
7. **AI Alerts (風險提醒)**：包含「事件標題」(Title)、「類型」(Select)、「等級」(Select)、「摘要」(Rich Text)、「處理狀態」(Status)。

> **注意**：請務必在 Notion 中將這些資料庫分享給您的 Integration (Connection)，否則 API 將無法讀取資料。

## 隱私與安全原則

- **不長期保存聊天紀錄**：本系統不連接資料庫保存群組完整對話，僅在記憶體中處理當下訊息。
- **個資保護**：涉及成績、繳費、請假原因等個資時，AI 會引導使用者私訊或轉交真人處理，不在群組公開回覆。
- **靜默規則**：在群組中，AI 僅在被 `@AI班主任` 提及、輸入特定指令，或偵測到高風險訊息時才會處理，避免干擾正常聊天。
