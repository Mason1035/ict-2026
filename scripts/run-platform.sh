#!/usr/bin/env bash
set -euo pipefail

PLATFORM_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PLATFORM_REPO"
PLATFORM_PYTHON="$PLATFORM_REPO/platform_backend/.venv/bin/python"

if [[ ! -x "$PLATFORM_PYTHON" ]]; then
  python3 -m venv platform_backend/.venv
  "$PLATFORM_PYTHON" -m pip install -e ./platform_backend
fi

if [[ ! -f apps/geohazard-demo/dist/index.html ]]; then
  cd apps/geohazard-demo
  npm ci
  npm run build
  cd "$PLATFORM_REPO"
fi

PLATFORM_PORT="${GEOHAZARD_PORT:-8000}"
printf '\n智哨防灾平台：http://127.0.0.1:%s\nAPI 文档：http://127.0.0.1:%s/docs\n按 Ctrl+C 停止。后端演示数据明确标记 MOCK，可用 GEOHAZARD_DEMO=0 禁用。\n\n' "$PLATFORM_PORT" "$PLATFORM_PORT"
exec "$PLATFORM_PYTHON" -m uvicorn geohazard_platform.main:app --host 127.0.0.1 --port "$PLATFORM_PORT"
