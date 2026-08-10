#!/bin/bash
# 本地开发：直接启动后端 (FastAPI:8585) + 4 个前端 SPA 的 vite dev server。
# 参考 skill-A2UI/start.sh。生产部署请用 ./deploy.sh (docker)。

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PID=""
PIDS=()

# app:port —— docs 是主入口
APPS=("docs:3585" "slides:3586" "pdf:3587" "markdown:3588" "sheets:3589")

cleanup() {
    echo ""
    echo -e "${YELLOW}正在关闭服务...${NC}"
    for pid in "$BACKEND_PID" "${PIDS[@]}"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
        fi
    done
    echo -e "${GREEN}所有服务已关闭${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  启动 AIOffice (开发模式)${NC}"
echo -e "${GREEN}========================================${NC}"

# 依赖检查
command -v uv  >/dev/null 2>&1 || { echo -e "${RED}未找到 uv，请先安装${NC}"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo -e "${RED}未找到 npm，请先安装 Node${NC}"; exit 1; }
[ -f "$PROJECT_DIR/.env" ] || echo -e "${YELLOW}提示: 未找到 .env（可从 .env.example 复制并填入模型 API Key）${NC}"

# 前端依赖
if [ ! -d "$PROJECT_DIR/frontend/node_modules" ]; then
    echo -e "${YELLOW}安装前端依赖 (npm install)...${NC}"
    (cd "$PROJECT_DIR/frontend" && npm install) || { echo -e "${RED}npm install 失败${NC}"; exit 1; }
fi

# 后端 (端口 8585)
echo -e "${YELLOW}启动后端 (端口 8585)...${NC}"
cd "$PROJECT_DIR/backend"
uv run uvicorn app.main:app --host 0.0.0.0 --port 8585 &
BACKEND_PID=$!

echo -e "${YELLOW}等待后端就绪...${NC}"
for i in $(seq 1 60); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo -e "${RED}后端进程已退出，启动失败${NC}"; cleanup
    fi
    if curl -sf "http://localhost:8585/healthz" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ 后端已就绪${NC}"; break
    fi
    [ "$i" -eq 60 ] && echo -e "${YELLOW}等待后端超时，仍继续启动前端${NC}"
    sleep 1
done

# 前端各 app 的 vite dev（各自代理 API 到 :8585）
for entry in "${APPS[@]}"; do
    app="${entry%%:*}"; port="${entry##*:}"
    echo -e "${YELLOW}启动前端 ${app} (端口 ${port})...${NC}"
    (cd "$PROJECT_DIR/frontend" && npm run dev --workspace "@genoffice/${app}") &
    PIDS+=($!)
done

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  服务已就绪${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}后端:      http://localhost:8585${NC}"
echo -e "${GREEN}文档(主):  http://localhost:3585${NC}"
echo -e "${GREEN}幻灯片:    http://localhost:3586${NC}"
echo -e "${GREEN}PDF:       http://localhost:3587${NC}"
echo -e "${GREEN}Markdown:  http://localhost:3588${NC}"
echo -e "${GREEN}表格:      http://localhost:3589${NC}"
echo -e "${YELLOW}注：pdf/markdown/slides/sheets 无独立登录，请先在文档端登录后经 ?doc= 打开${NC}"
echo ""
echo -e "${YELLOW}按 Ctrl+C 关闭所有服务${NC}"

wait
