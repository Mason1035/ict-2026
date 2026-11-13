#!/usr/bin/env bash
set -euo pipefail
: "${BOARD:?Usage: BOARD=user@192.168.1.20 [BOARD_REPO=/opt/ict-2026] bash scripts/build-and-push-dist.sh}"
BOARD_REPO="${BOARD_REPO:-/opt/ict-2026}"
# rsync passes a remote shell command; reject shell metacharacters in destinations.
if [[ ! "$BOARD" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.@-]*$ || ! "$BOARD_REPO" =~ ^/[a-zA-Z0-9_./-]+$ ]]; then
  printf 'BOARD / BOARD_REPO 格式无效；使用 user@IPv4 与无空格的绝对路径。\n' >&2
  exit 1
fi
BUILD_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BUILD_REPO/apps/geohazard-demo"
npm run build
rsync -av -- dist/ "$BOARD:$BOARD_REPO/apps/geohazard-demo/dist/"
printf '页面已复制到 %s:%s/apps/geohazard-demo/dist/\n' "$BOARD" "$BOARD_REPO"
