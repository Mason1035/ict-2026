#!/usr/bin/env bash
set -euo pipefail

PLATFORM_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PLATFORM_REPO"
PLATFORM_PYTHON="$PLATFORM_REPO/platform_backend/.venv/bin/python"
PLATFORM_APP="$PLATFORM_REPO/apps/geohazard-demo"
PLATFORM_PORT="${GEOHAZARD_PORT:-8000}"
PLATFORM_HOST="${GEOHAZARD_HOST:-127.0.0.1}"
PLATFORM_TOKEN="${GEOHAZARD_API_TOKEN:-}"
if [[ "$PLATFORM_HOST" != 127.0.0.1 && "$PLATFORM_HOST" != localhost && "$PLATFORM_HOST" != ::1 && -z "${PLATFORM_TOKEN//[[:space:]]/}" ]]; then
  printf '非 loopback GEOHAZARD_HOST 必须设置 GEOHAZARD_API_TOKEN。\n' >&2
  exit 1
fi

if [[ ! "$PLATFORM_PORT" =~ ^[0-9]{1,5}$ ]] || (( 10#$PLATFORM_PORT < 1 || 10#$PLATFORM_PORT > 65535 )); then
  printf 'GEOHAZARD_PORT 必须是 1–65535 之间的整数。\n' >&2
  exit 1
fi
PLATFORM_PORT=$((10#$PLATFORM_PORT))
export GEOHAZARD_PORT="$PLATFORM_PORT"

platform_check_python() {
  "$1" -c 'import sys; sys.exit("需要 Python 3.11+；可通过 GEOHAZARD_PYTHON 指定解释器。") if sys.version_info < (3, 11) else None'
}

if [[ ! -x "$PLATFORM_PYTHON" ]]; then
  PLATFORM_BOOTSTRAP_PYTHON="${GEOHAZARD_PYTHON:-python3}"
  if ! command -v "$PLATFORM_BOOTSTRAP_PYTHON" >/dev/null 2>&1; then
    printf '找不到 Python。请安装 Python 3.11+，或设置 GEOHAZARD_PYTHON。\n' >&2
    exit 1
  fi
  platform_check_python "$PLATFORM_BOOTSTRAP_PYTHON"
  "$PLATFORM_BOOTSTRAP_PYTHON" -m venv platform_backend/.venv
fi
platform_check_python "$PLATFORM_PYTHON"

PLATFORM_BACKEND_STAMP="$PLATFORM_REPO/platform_backend/.venv/.platform-dependencies-ready"
if [[ ! -f "$PLATFORM_BACKEND_STAMP" || platform_backend/pyproject.toml -nt "$PLATFORM_BACKEND_STAMP" ]] ||
   ! "$PLATFORM_PYTHON" -c 'import fastapi, uvicorn, pydantic, multipart, paho.mqtt.client, numpy, cv2, PIL, geohazard_platform' >/dev/null 2>&1; then
  printf '安装或更新后端依赖…\n'
  "$PLATFORM_PYTHON" -m pip install -e ./platform_backend
  touch "$PLATFORM_BACKEND_STAMP"
fi

PLATFORM_BUILD_NEEDED=0
if [[ ! -f "$PLATFORM_APP/dist/index.html" ]]; then
  PLATFORM_BUILD_NEEDED=1
elif [[ -n "$(find "$PLATFORM_APP/src" "$PLATFORM_APP/public" "$PLATFORM_APP/index.html" \
  "$PLATFORM_APP/package.json" "$PLATFORM_APP/package-lock.json" "$PLATFORM_APP/vite.config.ts" \
  "$PLATFORM_APP/tsconfig.json" -type f -newer "$PLATFORM_APP/dist/index.html" -print -quit)" ]]; then
  PLATFORM_BUILD_NEEDED=1
fi

if [[ "$PLATFORM_BUILD_NEEDED" == 1 ]]; then
  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    printf '构建页面需要 Node.js 20.19+ 或 22.12+（含 npm）。\n' >&2
    exit 1
  fi
  node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (!((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22)) { console.error("构建页面需要 Node.js 20.19+ 或 22.12+。"); process.exit(1); }'
  PLATFORM_FRONTEND_STAMP="$PLATFORM_APP/node_modules/.platform-dependencies-ready"
  if [[ ! -f "$PLATFORM_FRONTEND_STAMP" || "$PLATFORM_APP/package.json" -nt "$PLATFORM_FRONTEND_STAMP" || "$PLATFORM_APP/package-lock.json" -nt "$PLATFORM_FRONTEND_STAMP" ]]; then
    (cd "$PLATFORM_APP" && npm ci)
    touch "$PLATFORM_FRONTEND_STAMP"
  fi
  printf '构建最新页面…\n'
  (cd "$PLATFORM_APP" && npm run build)
fi

printf '\n智哨防灾平台：http://%s:%s\nAPI 文档：http://%s:%s/docs\nLAN 浏览器请使用板端 LAN IP。按 Ctrl+C 停止；GEOHAZARD_DEMO=0 禁用 MOCK 演示。\n\n' "$PLATFORM_HOST" "$PLATFORM_PORT" "$PLATFORM_HOST" "$PLATFORM_PORT"
exec "$PLATFORM_PYTHON" -m uvicorn geohazard_platform.main:app --host "$PLATFORM_HOST" --port "$PLATFORM_PORT"
