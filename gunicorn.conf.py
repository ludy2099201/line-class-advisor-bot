"""
Gunicorn 設定檔
Railway 部署時由 railway.toml 的 startCommand 載入。
"""
import os

# ── 網路設定 ────────────────────────────────────────────────────────────────
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", 2))
threads = int(os.environ.get("PYTHON_MAX_THREADS", 1))

# ── 逾時設定 ────────────────────────────────────────────────────────────────
# LINE Webhook 需在 30 秒內回應，設 60 秒留有餘裕
timeout = 60
keepalive = 5
graceful_timeout = 30

# ── 日誌設定（輸出到 stdout，Railway 可直接收集）──────────────────────────
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sµs'

# ── 程序設定 ────────────────────────────────────────────────────────────────
preload_app = True   # 預載 app，減少每個 worker 的記憶體用量
worker_class = "sync"
