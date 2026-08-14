# LINE Class Advisor Bot 部署與維運手冊

**適用版本：** `main` 分支，包含提交 `dffb3a9 feat: harden webhook and risk handling` 之後的安全與可靠性機制。

**部署目標：** Railway + LINE Messaging API + Notion API + Gemini API + Redis。

**文件擁有者：** 補習班系統管理者與指定維運人員。

**最後更新：** 2026-08-14（GMT+8）。

## 1. 目的、系統邊界與責任

本手冊說明如何把本專案安全部署至正式環境，以及如何在日常、異常與重大風險事件中維運。系統是一個部署於 LINE 班級群組的 Flask webhook 服務，提供 FAQ、課表、作業、請假引導、群組綁定、課後筆記及風險提醒等功能；它會存取 LINE、Notion、Gemini 與 Redis。[1]

系統的目標是協助教職員處理重複性行政溝通，**不是**取代教師、輔導人員、緊急服務或補習班既有的事故處置機制。特別是自傷、暴力威脅、霸凌與重大個資事件，Bot 只負責固定安全回覆、最小必要紀錄與通知人工；值班人員必須依機構核准的危機流程完成後續處置。

> **安全原則：** production 環境只要缺少必要設定，`/readyz` 就會回傳 `503`，LINE webhook 亦不會在缺少 Channel Secret 時接受事件。此設計是為了避免「可部署但不安全」的服務接收師生資料。

| 系統元件 | 職責 | 維運責任人 | 不應存放的內容 |
|---|---|---|---|
| Railway Web Service | 執行 Flask/Gunicorn、公開 HTTPS webhook、收集 stdout/stderr | 系統管理者 | API 金鑰、學生原文紀錄 |
| LINE Messaging API | 接收 webhook、回覆群組、推播給管理員 | LINE Channel 管理者 | Channel Secret 的明文截圖或聊天轉傳 |
| Notion | FAQ、課表、作業、請假、班級綁定、警示與筆記資料 | 行政資料管理者 | 不必要的完整對話抄本或 debug 資料 |
| Gemini API | FAQ fallback 與受限的風險分類 | 系統管理者 | 未去識別化的大量學生資料集 |
| Redis | session 與 webhook event 去重 | 系統管理者 | 長期業務主檔或人工處置結論 |
| GitHub | 原始碼、CI、Dependabot、變更審查 | 程式碼擁有者 | `.env`、token、匯出的真實個資資料 |

## 2. 架構與關鍵資料流

LINE 將 event POST 到 `/linebot`。程式先以未修改的 raw request body 驗證 `X-Line-Signature`，再以 `webhookEventId` 在 Redis 建立 24 小時的原子去重鎖；若同一 event 重送，系統會回 `200` 但不再次寫入 Notion 或再次回覆。LINE 官方要求驗簽前不可反序列化、替換或跳脫 request body，且簽章不符時不得處理 event。[4]

通過邊界檢查的 event 才會由 `LineRouter` 分派至各 handler。需要讀寫營運資料時會使用 Notion；需要語意回答或風險分類時才會呼叫 Gemini。Notion 的唯讀查詢具受上限的 429、529、5xx 與網路錯誤重試；資料寫入不自動重試，以降低未知結果時產生重複資料的風險。Notion 要求 client 處理 429/529、尊重 `Retry-After`，並以 queue、bounded backoff 與 jitter 避免重試風暴。[6]

```text
LINE Platform
  │ POST /linebot
  ▼
Raw body + HMAC signature validation
  │
  ├── Invalid / production not configured → 400 / 503，零業務副作用
  │
  ▼
Redis event claim (webhookEventId, 24 h TTL)
  │
  ├── Duplicate → 200，忽略重複 side effect
  ├── Redis unavailable in production → 503，請 LINE 重送
  │
  ▼
LineRouter → FAQ / 課表 / 作業 / 請假 / 筆記 / RiskHandler
  │                   │                     │
  ▼                   ▼                     ▼
LINE Reply/Push      Notion              Gemini
```

### 2.1 背景 webhook worker

web service 在完成驗簽、JSON 解析與 Redis event claim 後，會將單一 event 放入 `line_webhooks` queue 並快速回覆 `200`。同一 Railway project 的獨立 worker service 以相同 Redis 消費事件，才執行 `LineRouter`、Notion、Gemini 與 LINE side effect。worker 只處理一個 job；要提高吞吐量應新增 worker replica，而不是在 web process 內啟動 thread。[12]

整個 event 的預設 `WEBHOOK_JOB_MAX_RETRIES=0`。這是刻意的安全限制：事件包含可能非冪等的 Notion 寫入與一次性 LINE reply token，未知部分成功後重跑整個 job 可能製造重複紀錄或重複訊息。最終失敗工作會留在 RQ `FailedJobRegistry` 作為隔離區；必須先修復根因並人工核對 side effect，才能受控處理。既有 Notion 唯讀查詢與 LINE push 的局部重試不受此限制。[12]

## 3. 部署前權限與帳號準備

正式部署前，應指定至少一位技術維運人員與一位行政資料擁有者。技術維運人員需要 Railway service 的部署與 Variables 權限、LINE Developers Console 的 Channel 設定權限、Notion integration 的設定權限，以及 GitHub repository 的 pull request/Actions 管理權限。行政資料擁有者需要維護 Notion 資料內容與欄位的權限，但不應同時擁有 production secret 的匯出權限。

補習班處理學生與家長資料時，應有明確的資料最小化、權限分級、使用紀錄與事故應變流程。教育部的《短期補習班個人資料檔案安全維護計畫實施辦法》要求依特定目的界定資料範圍、設定不同權限、採取存取控制與異常使用監控，並留存必要的使用或軌跡資料。[9] 在上線前，請由機構確認值班名單、危機告警的備援聯絡人、個資事故窗口與資料保留規則。

| 外部服務 | 上線前應完成的設定 | 完成檢查 |
|---|---|---|
| LINE Developers | 建立 Messaging API channel、取得 access token 與 channel secret、啟用 webhook | 可在 Console 看到 webhook 送達統計；secret 僅存在 secret manager |
| Notion | 建立資料庫、邀請 integration、限制資料庫分享範圍 | integration 僅能讀寫必要資料庫，不能存取整個 workspace |
| Gemini | 建立 API key、確認模型可用與配額 | key 僅存在 Railway Variables；非 production 不使用 production key |
| Railway | 建立 production service、設定 GitHub source、加入 Redis service 或 Plugin | Web service 與 Redis 位於正確 environment，並有可讀取 log 的維運帳號 |
| GitHub | 啟用 Actions、Dependabot、Secret Scanning/Push Protection（若方案支援） | PR 會執行測試與 dependency audit；金鑰提交被阻擋 |

## 4. Notion 資料庫準備與 schema 管理

Notion 欄位名稱在目前程式中具有業務意義；管理者變更欄位名稱或型別前，應先在 staging 驗證。請將 integration 分享給下列必要資料庫，而不是上層 workspace 或無關私人頁面。欄位名稱應保持一致，避免程式讀取空值或寫入失敗。

| 資料庫環境變數 | 用途 | 最小必要欄位 |
|---|---|---|
| `NOTION_DB_FAQ` | FAQ 回覆 | 問題（Title）、答案（Rich Text）、關鍵字（Rich Text 或 Multi-select）、啟用（Checkbox） |
| `NOTION_DB_SCHEDULE` | 每日課表 | 課程標題（Title）、上課時段（Date）、課程主題（Rich Text）、教室（Rich Text）、備註（Rich Text） |
| `NOTION_DB_HOMEWORK` | 作業 | 作業名稱（Title）、科目（Select）、截止日（Date）、內容（Rich Text）、班級（Rich Text） |
| `NOTION_DB_EXAMS` | 考試範圍 | 考試名稱（Title）、科目（Select）、考試日期（Date）、範圍（Rich Text）、班級（Rich Text） |
| `NOTION_DB_LEAVES` | 請假紀錄 | 學生姓名（Title）、請假日期（Date）、原因（Rich Text）、狀態（Status） |
| `NOTION_DB_LINE_GROUPS` | 群組與班級對照 | 群組名稱（Title）、LINE groupId（Rich Text）、對應班級（Relation 或既有程式支援格式） |
| `NOTION_DB_AI_ALERTS` | 風險事件 | 事件標題（Title）、類型（Select）、等級（Select）、摘要（Rich Text） |
| `NOTION_DB_STAFF` | 教職員資料 | 依機構實際 schema；僅授權必要角色 |
| `NOTION_DB_CLASSES` | 班級資料 | 班級名稱與供群組綁定使用的識別資料 |
| `NOTION_DB_NOTES` | 課後筆記 | 由現有 `NoteHandler`/`NotionService` 所需的學生、日期、課程、表現、情緒、內容與追蹤欄位 |

Notion API 的平均 connection 限制為每秒三個請求，並存在 workspace 共用限制；所以不得以大量同時查詢替代快取或批次規劃。[6] 若新增資料庫欄位或調整型別，應先建立 staging database、執行測試，並在變更窗口後觀察 `Notion query failed`、`validation_error` 與 429/529 日誌。

## 5. 環境變數與 secret 管理

請以 repository 的 `.env.example` 為基礎建立本機 `.env`，但**不要**把 `.env` 提交至 Git。production 的值應只存在 Railway Variables 或組織核准的 secret manager。以下表格列出名稱與用途；表中絕不應填入真實值。

| 變數 | production 必要性 | 用途與設定原則 |
|---|---|---|
| `APP_ENV` | 必填 | 設為 `production`；此值啟用 fail-closed webhook 與 production Redis 政策 |
| `LINE_CHANNEL_ACCESS_TOKEN` | 必填 | LINE 回覆與 push token；輪替後需更新 Railway 並重新部署 |
| `LINE_CHANNEL_SECRET` | 必填 | 驗證 webhook HMAC；不可記錄、不可傳送到聊天工具 |
| `NOTION_API_TOKEN` | 必填 | Notion integration token；僅分享必要資料庫 |
| `GEMINI_API_KEY` | 必填 | Gemini 呼叫；依模型、配額與帳務設定管理 |
| `ADMIN_LINE_USER_ID` | 必填 | 接收風險人工告警的管理員 user ID；建議另有機構備援流程 |
| `ADMIN_LINE_USER_IDS` | 選填 | 其他可執行群組綁定與課後筆記操作的管理員 LINE user ID，以逗號分隔 |
| `STAFF_LINE_USER_IDS` | 選填 | 可在私訊新增與查詢課後筆記的教職員 LINE user ID，以逗號分隔；未設定時僅主要管理員可操作 |
| `REDIS_URL` | 必填 | production session、webhook 去重與低敏感 FAQ／開課班級快取；不可用時 `/readyz` 應視為不可接流量 |
| `FAQ_CACHE_TTL_SECONDS`、`CLASS_LIST_CACHE_TTL_SECONDS` | 選填 | 僅控制 FAQ 與開課班級清單快取，預設分別為 900 與 300 秒；不得用於學生筆記、請假、群組或風險資料 |
| `WEBHOOK_QUEUE_NAME` | web／worker 必填 | 兩個 service 必須完全相同，預設 `line_webhooks` |
| `WEBHOOK_JOB_TIMEOUT_SECONDS` | 選填 | 單一 worker job 的最長執行秒數，預設 120 |
| `WEBHOOK_JOB_MAX_RETRIES` | 選填 | 預設 0；整個 event 未具完整跨服務冪等性前不得提高 |
| `WEBHOOK_JOB_RETRY_INTERVALS` | 選填 | 僅在未來安全啟用 job retry 後才生效，預設 `10,60,300` |
| `LLM_MODEL` | 選填 | 未設時使用程式預設 `gemini-3.1-flash-lite`；變更前先在 staging 評估 |
| `NOTION_DB_*` | 依功能必填 | 填入對應資料庫 ID；未啟用功能可先不設，但應確認 handler 行為 |
| `CRAM_SCHOOL_NAME`、`BOT_NAME` | 建議設定 | 顯示用名稱；不得填寫個人資料 |
| `SESSION_TTL_SECONDS` | 選填 | session TTL，預設 1800 秒；調整需兼顧請假流程與資料最小化 |
| `LOG_LEVEL`、`WEB_CONCURRENCY`、`PORT` | 由平台/維運設定 | 可依 Railway 與容量調整；不要把 token 放入任何 log 設定 |

在 Railway Variables 輸入值後，先確認變數名稱完全匹配，再執行部署。變數缺失時 `/readyz` 會回應 `missing_config` 的**名稱**，不會回傳其值；這是排障時應使用的唯一診斷方式。

## 6. 本機開發與 staging 驗證

專案由 `.python-version` 指定 Python 3.11。建議每位開發者使用獨立 virtual environment，並且只以測試 token 或 mock 執行。不可在本機 `.env` 填入 production 學生資料或 production API key。

```bash
# 1. 取得主分支
# git clone <repository-url>
cd line-class-advisor-bot

# 2. 使用 Python 3.11 建立隔離環境
python3.11 -m venv .venv
source .venv/bin/activate

# 3. 安裝執行與開發依賴
pip install -r requirements.txt -r requirements-dev.txt

# 4. 建立本機設定，僅填入測試用值
cp .env.example .env
# 編輯 .env：APP_ENV=development

# 5. 執行測試與語法檢查
python -m compileall -q app scripts main.py
pytest -q
pip-audit -r requirements.txt
# 在已載入 staging 或 production Notion 設定的受控環境中執行；僅讀取 metadata。
python scripts/validate_notion_schema.py

# 6. 啟動本機服務
gunicorn main:app --config gunicorn.conf.py
```

開發模式允許 Redis 不存在時使用 In-Memory session 與 event 去重，以方便本機測試；**production 不允許**以此作為 Redis 故障的替代。課後筆記與群組綁定採預設拒絕的 allowlist：筆記只允許已授權帳號以私訊操作，群組綁定僅允許管理員。系統會以雜湊記錄授權拒絕事件，且在送往模型前遮罩常見 email、臺灣手機與身分證字號；此遮罩不是完整 DLP 替代方案。測試應涵蓋有效/無效簽章、重複 event、Notion 429、LINE 409、危機固定回覆與未授權資料存取。Flask 官方建議透過 pytest fixture 建立 app 與 test client；本專案已在 `tests/conftest.py` 實作這個基礎。[8]

## 7. Railway 正式部署程序

本專案以根目錄的 `railway.toml` 描述建置與啟動設定，使用 Nixpacks 建置並以 Gunicorn 啟動 `main:app`。Railway 在每次部署時會讀取 `railway.toml`，且程式碼中的設定會覆寫 Dashboard 對該次部署的相同設定。[2] 目前設定使用 `/readyz` 作為 healthcheck path；Railway 只有在此端點回 `200` 後才會將新 deployment 設為 active。[3]

### 7.1 初次部署

請先在 Railway 建立 Project 與 production environment，再建立 Web Service 並連接 GitHub repository 的 `main` 分支。完成後加入 Redis；確認 Railway 注入或自行設定 `REDIS_URL`。接著在 Variables 貼入第 5 節所列的 production 值，特別是 `APP_ENV=production`。完成後觸發首次 deploy，打開 Deployment Logs，等待 build、Gunicorn 啟動與 healthcheck 通過。

| 步驟 | Railway 操作 | 預期證據 | 若失敗時的第一檢查點 |
|---|---|---|---|
| 1 | 建立 Web Service 並連接 `main` | source 指向正確 repository/branch | 是否選到 fork、舊 branch 或錯誤 service |
| 2 | 連接 Redis service 或設定 `REDIS_URL` | Variables 有非空 Redis URL | `/readyz` 的 `missing_config` 是否含 `REDIS_URL` |
| 3 | 設定所有 production Variables | `/readyz` 回 `{"status":"ready"...}` | 變數名稱拼字、scope 與 environment 是否正確 |
| 4 | 確認 deploy 設定 | logs 顯示 Gunicorn 綁定 `$PORT` | `railway.toml` 是否在 root、`PORT` 是否被 Railway 注入 |
| 5 | 等待 healthcheck | Deployment 顯示 Success | logs 是否有 import error、secret 缺失或 Redis 連線問題 |
| 6 | 記錄公開 domain | 可取得 `https://<domain>/livez` | domain 是否已生成並正確指向 service |

Railway healthcheck 僅在 deployment 啟動階段用來判定新版本是否可接流量，不是持續監控機制；因此 production 仍應設定外部 uptime monitor 定期呼叫 `/livez` 與 `/readyz`。[3]

### 7.2 LINE Webhook 設定與驗證

在 LINE Developers Console 將 Webhook URL 設為：

```text
https://<railway-public-domain>/linebot
```

先在 Railway 確認 `/readyz` 為 `200`，再啟用 LINE webhook。LINE 會以 Channel Secret 對原始 request body 產生 HMAC-SHA256 簽章；系統會在任何 JSON parse 前檢驗 `X-Line-Signature`。若透過 proxy、middleware 或自訂 logging 修改 body，驗簽可能失敗。[4]

完成後使用 LINE Console 的 Verify 功能及實際測試帳號各執行一次。成功標準是 LINE Console 顯示正常、Railway logs 出現 webhook event 處理紀錄、且無 `Invalid LINE signature`、`Webhook verification is not configured` 或 `event deduplication is unavailable`。

### 7.3 上線驗收清單

| 測試案例 | 預期結果 | 不可接受結果 |
|---|---|---|
| `GET /livez` | HTTP 200、`status=alive` | 連線失敗、5xx |
| `GET /readyz` | production 下 HTTP 200、`status=ready` | `missing_config` 非空、HTTP 503 |
| LINE Console Verify | 成功 | 400、503 或 timeout |
| 群組「今日課表」 | 僅回覆綁定班級的公開資訊 | 出現其他班級或個資 |
| 私訊請假 | 依多輪流程收集最小必要資料 | 在群組要求姓名、日期、原因 |
| 同一測試 event 重送 | 只產生一次回覆/Notion side effect | 重複請假、重複筆記、重複警報 |
| 明確高風險測試語句 | 固定安全文案、人工告警、Notion 警示 | 模型自訂危機文案、未通知人工 |

## 8. 健康檢查、日誌與監控

系統提供三個端點，各自用途不同。不要以 `/health` 的 `200` 作為所有功能均可用的唯一證據；部署與監控應優先讀取 `/readyz`。

| 端點 | HTTP 200 的意義 | HTTP 503 的意義 | 建議用途 |
|---|---|---|---|
| `/livez` | Flask process 可回應 | process 或路由有問題 | 外部 uptime 基本存活監控 |
| `/readyz` | production 所需設定已齊全 | production 缺少關鍵設定 | Railway deploy healthcheck、主要 readiness monitor |
| `/health` | 相容性狀態端點；即使 degraded 仍維持 200 | 一般不應用於 readiness | 舊有 Railway/監控相容性與人工診斷 |

現有日誌輸出至 stdout/stderr，由 Railway 收集。日常排障時應使用 event ID、LINE request ID、HTTP status、service 名稱與錯誤類型查詢，而非搜尋學生姓名或完整訊息。以下字串是優先關注的訊號。

| 日誌或症狀 | 含義 | 初步動作 |
|---|---|---|
| `Invalid LINE signature` | secret 不符、body 被改動或非 LINE 請求 | 比對 Railway 的 secret 與 LINE Console；檢查 proxy 是否改 body；不要記錄 secret |
| `Duplicate LINE webhook event ignored` | LINE 重送已被安全去重 | 通常正常；若大量增加，檢查 webhook 延遲與 LINE error statistics |
| `event deduplication is unavailable` | production Redis 去重無法使用 | 視為可用性事件；檢查 Redis、網路與 `REDIS_URL`，修復前不要繞過 |
| `Risk alert push was not accepted` | LINE 管理員警報未被接受 | 依機構備援流程人工通知，檢查 admin user ID、channel 權限與 LINE API 回應 |
| `Notion query failed` 或 429/529 | Notion schema、授權或速率限制問題 | 檢查欄位、integration 分享、`Retry-After`、流量尖峰與近期 schema 變更 |
| Gemini 呼叫失敗或空結果 | key、模型、配額或上游暫時故障 | 檢查 Gemini console；風險路徑會保守轉成人工確認 |

## 9. 日常維運節奏

維運不是只在故障時登入平台。請建立有責任人的固定節奏，並將每次異常、變更及值班名單更新記錄在內部系統。

| 頻率 | 必做事項 | 完成證據 |
|---|---|---|
| 每日上課日前 | 檢查 `/readyz`、Railway 最近 deployment、關鍵 error log、管理員 LINE 告警可用性 | 維運日誌記錄時間與狀態 |
| 每週 | 檢查 GitHub Actions、Dependabot PR、Notion 欄位變動、Redis 使用量與失效事件 | PR/Issue 或內部檢查表 |
| 每月 | 演練 webhook 驗簽、重送去重、Notion 限流、管理員告警與回滾；盤點成員權限 | 演練紀錄與改善事項 |
| 每季或人員異動 | 輪替 secrets、移除離職人員 Notion/LINE/Railway/GitHub 權限、複查資料保留期 | 權限盤點與輪替紀錄 |
| 每次 schema 或模型變更前 | 在 staging 執行測試、人工抽查、發佈計畫與回滾計畫 | PR、測試結果、核准紀錄 |

GitHub Actions 目前在 push 與 pull request 上執行 syntax check、pytest 及 `pip-audit`。Dependabot 會每週對 pip 與 GitHub Actions 生態系提出更新 PR；請不要直接自動合併所有依賴更新，而應待 CI 通過後由維運人員檢閱。GitHub 建議把 Dependabot update 納入既有 review 和測試流程。[10]

## 10. 事故處置 Runbook

### 10.1 `/readyz` 回 503

第一步，讀取 response 中的 `missing_config` 名稱，確認 Railway Variables 是否在 production environment 設定。第二步，若缺少 `REDIS_URL`，確認 Redis service 是否健康、網址是否可供 Web Service 使用。第三步，修正後重新部署，直到 `/readyz` 回 200。不得藉由把 `APP_ENV` 改回 development 來規避 production 安全門檻。

### 10.2 LINE webhook 400 或驗簽失敗

確認 Railway 的 `LINE_CHANNEL_SECRET` 與 LINE Developers Console 的 Channel Secret 屬於同一 channel。檢查是否有 proxy/middleware 讀取並重寫 request body，或是否以 JSON 物件重新序列化後才驗簽。不要在 ticket、log 或聊天訊息貼出 secret。修正後使用 LINE Console Verify 與測試訊息再次驗證。

### 10.3 Redis 不可用或 event deduplication 失敗

production 下，系統會回 503 讓 LINE 後續重送，而不是以 instance-local state 冒重複 side effect 的風險。先檢查 Redis service 狀態、網路連線、`REDIS_URL` 及容量。恢復後觀察 `Duplicate LINE webhook event ignored` 是否出現，確認重送 event 沒有重複建立請假、筆記或警報。

### 10.4 Notion 429、529、5xx 或資料讀不到

Notion client 對唯讀查詢會尊重 `Retry-After` 並受限重試；不要在 incident 中手動不斷重送訊息製造額外流量。檢查 Notion status、integration 是否仍受邀於目標 database、欄位名稱/型別是否遭修改，以及流量是否突然增加。若是寫入失敗，因程式不自動重試，維運人員應以 event ID、Notion 紀錄與 LINE 對話確認是否需要受控補件，避免直接重送造成重複資料。

### 10.5 高風險訊息或人工告警未送達

對明確危機訊號，系統固定回覆求助與緊急資源資訊，並嘗試發送管理員告警。值班人員仍必須依補習班核准的危機流程處理，不可只依賴 Bot 狀態。若看到 `Risk alert push was not accepted` 或沒有管理員 ACK，立即使用機構備援聯絡方式通知值班主管；再檢查 `ADMIN_LINE_USER_ID`、LINE channel 的 push 能力與管理員是否仍可接收訊息。臺灣的 1925 安心專線提供 24 小時心理諮詢；在可能存在立即危險時，應由人工依既定程序聯絡當地緊急服務或適當專業人員。[11]

### 10.6 個資疑慮或疑似外洩

立即停止不必要的資料共享與該功能的後續寫入，保全最小必要日誌和時間線，通知機構指定的個資負責人，並依既定事故應變程序處置。不要把原始學生資料複製到 issue、公開 log、聊天群組或未加密 spreadsheet。教育部規範要求補習班有事故控制、調查、通知與通報的應變機制；機構應依實際情況與主管機關要求採取後續行動。[9]

## 11. 發版、回滾與變更管理

所有 production 變更應由 feature branch 發起 pull request，並在合併前完成 CI、人工 code review、Notion schema 檢查和必要的 staging 測試。不要直接在 Railway Console 編輯程式碼或修改與 repository 不一致的 start command；`railway.toml` 是部署設定的版本化來源。[2]

| 情境 | 建議程序 | 驗證 |
|---|---|---|
| 一般程式變更 | feature branch → PR → CI → review → merge `main` → Railway deploy | `/readyz` 200、LINE verify、關鍵流程 smoke test |
| 依賴安全更新 | Dependabot PR → CI → review → merge | `pip-audit`、pytest、deployment logs 正常 |
| Notion schema 變更 | staging schema → staging test → 變更窗口 → production schema | 查詢與寫入成功，無 validation error |
| 緊急回滾 | 在 Railway 重新部署前一個已知良好 deployment，並建立追蹤 issue | `/readyz` 200、webhook 可驗簽、事件未重複 |
| Git 回滾 | 建立 revert commit，經 CI 與 review 後合併 | 不使用 force push 改寫 production 歷史 |

Railway 的 deployment healthcheck 在新版本可回 200 前不會切換流量，但不會在上線後持續監控；因此回滾後仍要以外部 monitor 與 LINE smoke test 確認服務持續可用。[3]

## 12. 目前限制與下一階段改善

目前 webhook 路徑仍在 HTTP request 內同步執行 router、Notion 與 Gemini；儘管 event 去重降低了重送副作用，下一階段仍應導入背景 worker、queue 與 dead-letter 管理，讓 webhook 更快 ACK。角色型授權、學生資料遮罩、Notion schema contract、資料快取與 FAQ 黃金測試集也仍是下一輪優先項目。

在這些工作完成前，務必限制具敏感資料功能的使用者範圍、定期抽查群組回覆、並讓人類行政/教師保留最終決策權。任何模型、資料庫或平台設定改動都應被視為 production 變更，需有測試、審查與回滾計畫。

## 參考資料

[1]: https://github.com/ludy2099201/line-class-advisor-bot "line-class-advisor-bot 原始碼與 README"
[2]: https://docs.railway.com/reference/config-as-code "Railway Docs — Config as Code"
[3]: https://docs.railway.com/guides/healthchecks "Railway Docs — Healthchecks"
[4]: https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/ "LINE Developers — Verify webhook signature"
[5]: https://developers.line.biz/en/docs/messaging-api/retrying-api-request/ "LINE Developers — Retry failed API requests"
[6]: https://developers.notion.com/reference/request-limits "Notion Docs — Request limits"
[7]: https://ai.google.dev/gemini-api/docs/structured-output "Gemini API — Structured outputs"
[8]: https://flask.palletsprojects.com/en/stable/testing/ "Flask Documentation — Testing Flask Applications"
[9]: https://edu.law.moe.gov.tw/LawContent.aspx?id=GL001305 "教育部 — 短期補習班個人資料檔案安全維護計畫實施辦法"
[10]: https://docs.github.com/en/code-security/tutorials/secure-your-dependencies/automate-dependabot-with-actions "GitHub Docs — Automate Dependabot with Actions"
[11]: https://www.mohw.gov.tw/cp-16-19209-1.html "衛生福利部 — 全年無休的自殺防治守護者：安心專線 1925"
