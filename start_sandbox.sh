#!/usr/bin/env bash
# 启动 OpenSandbox 服务端（保持运行）。
# 沙箱由后端连接池按每租户自动创建，无需在此手动 create。
set -euo pipefail

# 幂等：已在跑就直接退出
if curl -sf http://localhost:8080/health >/dev/null 2>&1; then
  echo "服务端已在 :8080 运行，无需重复启动。"
  exit 0
fi

echo "==> 启动服务端（日志输出到控制台，Ctrl+C 停止）..."
uvx opensandbox-server &
SERVER_PID=$!

echo "==> 等待服务端就绪..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8080/health >/dev/null 2>&1; then
    echo "    服务端已就绪 (PID: ${SERVER_PID})"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "    超时，服务端未能启动。"
    kill "${SERVER_PID}" 2>/dev/null || true
    exit 1
  fi
  sleep 1
done

echo ""
echo "服务端保持运行中。停止：kill ${SERVER_PID}（或 Ctrl+C）"
wait "${SERVER_PID}"
