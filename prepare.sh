#!/usr/bin/env bash
# 准备 OpenSandbox 环境（Docker 后端）。详见 docs/OpenSandBox本地部署.md
set -euo pipefail

# 加载 .env 配置
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "${SCRIPT_DIR}/.env" ]; then
  set -a
  source "${SCRIPT_DIR}/.env"
  set +a
fi

MIRROR="${OSB_MIRROR:-docker.1ms.run}"
API_KEY="${OSB_API_KEY:-123456}"
CONFIG="${HOME}/.sandbox.toml"

echo "==> 检查 Docker..."
docker info >/dev/null 2>&1 || { echo "Docker 未运行，请先启动 Docker Desktop。"; exit 1; }

echo "==> 拉取镜像..."
echo "==> 拉取 execd 镜像（opensandbox 注入每个沙箱的执行守护进程）..."
docker pull "${MIRROR}/opensandbox/execd:v1.0.20"
docker tag  "${MIRROR}/opensandbox/execd:v1.0.20" opensandbox/execd:v1.0.20

echo "==> 构建沙箱镜像 my-sandbox:latest（python:3.12 + pandoc + 技能脚本）..."
docker build -t my-sandbox:latest "${SCRIPT_DIR}/sandbox-image"

echo "==> 写入服务端配置: ${CONFIG}"
if [ ! -f "${CONFIG}" ]; then
  uvx opensandbox-server init-config "${CONFIG}" --example docker
fi
# 确保 [server] 包含 host/port/api_key
python3 - "$CONFIG" "$API_KEY" <<'PY'
import sys, re, pathlib
path, key = sys.argv[1], sys.argv[2]
t = pathlib.Path(path).read_text()
if "[server]" not in t:
    t += f'\n[server]\nhost = "0.0.0.0"\nport = 8080\napi_key = "{key}"\n'
else:
    def ensure(text, k, v):
        pat = re.compile(rf'^{k}\s*=.*$', re.M)
        return pat.sub(f'{k} = {v}', text) if pat.search(text) else re.sub(r'(\[server\][^\[]*)', rf'\1{k} = {v}\n', text, count=1)
    t = ensure(t, "host", '"0.0.0.0"')
    t = ensure(t, "port", "8080")
    t = ensure(t, "api_key", f'"{key}"')
pathlib.Path(path).write_text(t)
print("配置写入完成")
PY

echo "==> 配置 CLI..."
osb config init 2>/dev/null || true
osb config set connection.domain localhost:8080
osb config set connection.protocol http
osb config set connection.api_key "\"${API_KEY}\""
osb config set connection.request_timeout 180

cat <<EOF

完成（一次性准备）。下一步：
  1. 启动沙箱服务端：  ./start_sandbox.sh   （保持运行）
  2. 启动应用：        ./start.sh           （后端会自动向服务端创建每租户沙箱）
EOF
