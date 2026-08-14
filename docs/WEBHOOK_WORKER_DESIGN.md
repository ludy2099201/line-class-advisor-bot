# Webhook 背景 Worker 設計決策

## 目的

Web service 只負責驗證 LINE 原始 request body、解析 JSON、以 Redis 宣告 `webhookEventId` 並將事件放入 Redis queue。獨立 worker service 在相同 Railway environment 內取得工作後，才建立 Flask app、初始化 `LineRouter` 並執行 Notion、Gemini 與 LINE side effect。web 與 worker 必須使用相同的 `REDIS_URL` 與 queue 名稱。

## 安全資料邊界

Queue 只應存在於受 Railway private network 保護且受控的 Redis。作業使用 RQ JSON serializer，避免預設 pickle serializer 對不受信任 Redis 資料的反序列化風險。日誌僅記錄 job ID、event type、事件短雜湊與例外類型，不記錄 LINE 原始文字、token、Notion payload 或 traceback。

## 可靠性與冪等性

`webhookEventId` 去重在成功入列後保留 24 小時。若 queue 無法使用，web service 釋放尚未入列事件的 claim 並回傳 503，使 LINE 可以安全重送。若 worker 最終失敗，工作由 RQ `FailedJobRegistry` 隔離；維運人員必須先修復根因，再依 job ID 受控判斷是否重送。

> **重要限制：** RQ 對「整個 LINE event」自動重試會重新執行 Notion 寫入與 LINE reply；目前這些 side effect 並非全部具備跨服務冪等鍵，且 LINE reply token 只能使用一次。因此，背景 webhook job 的預設重試次數應為 **0**。既有的 Notion 唯讀查詢與 LINE push 呼叫仍保留各自已實作的安全重試。只有在每個寫入路徑都具備可驗證的冪等性後，才能把 `WEBHOOK_JOB_MAX_RETRIES` 提高到大於 0。

## Railway 佈署

web service 繼續使用 `railway.toml` 與 `/readyz` healthcheck。worker service 使用獨立 `railway.worker.toml`，沒有 public domain 或 HTTP healthcheck，啟動 `python worker.py`。worker 應使用單一處理槽與 scheduler；需要更多併行量時，以新增 worker replica 擴展，而不是在 web process 內啟動 thread。

## 維運指標

應記錄 `LINE webhook event enqueued`、`Webhook job completed`、`retry_scheduled` 與 `dead_lettered`。在 production 開始前，應對成功事件、queue 不可用、worker 不可用與未預期 job 失敗分別測試，並確認不會重複寫入 Notion 或重複回覆使用者。
