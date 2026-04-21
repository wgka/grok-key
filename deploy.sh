#!/usr/bin/env bash
# 一键部署：拉取 Git -> 停止端口上的服务 -> 后台重启 server.py
# 用法（在项目根目录）:
#   chmod +x deploy.sh && ./deploy.sh
# 环境变量（可选）:
#   PORT=9000 PYTHON=python3 LOG_FILE=/var/log/grok-key.log ./deploy.sh
#   GIT_REMOTE=origin GIT_BRANCH=main ./deploy.sh   # 指定拉取分支；不设则拉当前分支

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-8000}"
PYTHON="${PYTHON:-python3}"
LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/deploy.log}"
PID_FILE="${PID_FILE:-$SCRIPT_DIR/.deploy.pid}"
GIT_REMOTE="${GIT_REMOTE:-origin}"
GIT_BRANCH="${GIT_BRANCH:-}"

stop_listeners() {
  local pids
  pids="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    echo "No process listening on port $PORT"
    return 0
  fi
  echo "Stopping listener(s) on port $PORT: $pids"
  kill $pids 2>/dev/null || true
  sleep 1
  pids="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Force killing: $pids"
    kill -9 $pids 2>/dev/null || true
  fi
}

echo "==> Git pull"
if [[ -n "$GIT_BRANCH" ]]; then
  git pull "$GIT_REMOTE" "$GIT_BRANCH"
else
  git pull "$GIT_REMOTE" "$(git rev-parse --abbrev-ref HEAD)"
fi

echo "==> Stop service (port $PORT)"
stop_listeners

echo "==> Start server (port $PORT, log $LOG_FILE)"
nohup "$PYTHON" server.py "$PORT" >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
echo "Started PID $(cat "$PID_FILE")"

sleep 1
if curl -sf "http://127.0.0.1:$PORT/healthz" >/dev/null; then
  echo "healthz OK"
else
  echo "WARN: healthz not ready; see $LOG_FILE"
fi
