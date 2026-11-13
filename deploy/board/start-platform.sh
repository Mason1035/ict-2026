#!/usr/bin/env bash
# Use already provisioned board dependencies and PC-built dist. No installs/builds.
set -eo pipefail
BOARD_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$BOARD_REPO"
if [[ -f /usr/local/Ascend/ascend-toolkit/set_env.sh ]]; then
  source /usr/local/Ascend/ascend-toolkit/set_env.sh
fi
export GEOHAZARD_DEMO="${GEOHAZARD_DEMO:-0}"
if [[ ! -f apps/geohazard-demo/dist/index.html ]]; then
  printf '缺少前端 dist；请先在 PC 运行 scripts/build-and-push-dist.sh。\n' >&2
  exit 1
fi
# Settings validates the bind/token pair before launching a listener.
platform_backend/.venv/bin/python -c 'from geohazard_platform.settings import Settings; Settings()'
exec platform_backend/.venv/bin/python -m uvicorn geohazard_platform.main:app \
  --host "${GEOHAZARD_HOST:-127.0.0.1}" --port "${GEOHAZARD_PORT:-8000}"
