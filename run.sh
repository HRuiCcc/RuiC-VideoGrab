#!/usr/bin/env bash
# VideoGrab 一键启动：首次运行自动创建 venv、安装依赖和无头浏览器
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "[VideoGrab] 首次运行，创建虚拟环境并安装依赖…"
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi
# 抖音下载依赖无头 Chromium，未安装则自动装（约 95MB）
CHROME_BIN=$(.venv/bin/python - <<'EOF' 2>/dev/null
from playwright.sync_api import sync_playwright
try:
    with sync_playwright() as p:
        print(p.chromium.executable_path)
except Exception:
    pass
EOF
)
if [ -z "$CHROME_BIN" ] || [ ! -e "$CHROME_BIN" ]; then
  echo "[VideoGrab] 首次运行：安装无头浏览器（用于抖音下载，约 95MB）…"
  .venv/bin/playwright install chromium
fi
echo "[VideoGrab] 启动 http://127.0.0.1:8900"
exec .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8900
