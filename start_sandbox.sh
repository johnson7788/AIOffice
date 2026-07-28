#!/usr/bin/env bash
# 启动 OpenSandbox 服务端（保持运行）。
# 沙箱由后端按每租户自动创建，无需在此手动 create。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
UPLOADS_DIR="$PROJECT_DIR/backend/uploads"
CONFIG="$PROJECT_DIR/.sandbox.toml"   # 仓库本地配置（已 gitignore），不碰用户全局 ~/.sandbox.toml

# 幂等：已在跑就直接退出
if curl -sf http://localhost:8080/health >/dev/null 2>&1; then
  echo "服务端已在 :8080 运行，无需重复启动。"
  exit 0
fi

# 每租户把 backend/uploads/<user> RW 挂进沙箱，服务端有 host-path 白名单：
# [storage] allowed_host_paths 为空 = 拒绝所有挂载（空列表≠放行，见 validators.py）。
# 这里首启生成 docker 默认配置，并每次把白名单幂等改写为本机 uploads 绝对路径——
# 换机器/换目录都自动正确，用户无需手改任何文件。
mkdir -p "$UPLOADS_DIR"
[ -f "$CONFIG" ] || uvx opensandbox-server init-config "$CONFIG" --example docker >/dev/null
# 传 api_key：docker 示例默认把 api_key 注释掉 → 空 key 会触发「不安全服务端」交互确认而卡住启动。
# 与 .env 的 SANDBOX_API_KEY 保持一致（本地开发默认 123456），非交互直启。
API_KEY="${SANDBOX_API_KEY:-123456}"
python3 - "$CONFIG" "$UPLOADS_DIR" "$API_KEY" <<'PY'
import re, sys, pathlib
cfg, uploads, api_key = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
t = cfg.read_text()

def upsert(text, key, value, section):
    line = f'{key} = {value}'
    pat = rf'(?m)^\s*#?\s*{key}\s*=.*$'                   # 含被注释的例行；就地改写第一处
    if re.search(pat, text):
        return re.sub(pat, line, text, count=1)
    return text + f'\n[{section}]\n{line}\n'              # 完全缺失 → 兜底补段

t = upsert(t, 'allowed_host_paths', f'["{uploads}"]', 'storage')
t = upsert(t, 'api_key', f'"{api_key}"', 'server')
cfg.write_text(t)
PY

echo "==> 启动服务端（config: ${CONFIG}，日志输出到控制台，Ctrl+C 停止）..."
uvx opensandbox-server --config "$CONFIG" &
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
