#!/bin/bash

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    echo ""
    echo -e "${YELLOW}正在关闭服务...${NC}"

    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        kill "$BACKEND_PID" 2>/dev/null
        wait "$BACKEND_PID" 2>/dev/null
        echo -e "${GREEN}✓ 后端已关闭${NC}"
    fi

    if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        kill "$FRONTEND_PID" 2>/dev/null
        wait "$FRONTEND_PID" 2>/dev/null
        echo -e "${GREEN}✓ 前端已关闭${NC}"
    fi

    echo -e "${GREEN}所有服务已关闭${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  启动科研助手${NC}"
echo -e "${GREEN}========================================${NC}"

# 清理上一代残留的孤儿沙箱容器（内存态 pool 重启后无法接管，起新的前先清）
echo -e "${GREEN}  清理上一代残留的孤儿沙箱容器"
docker rm -f $(docker ps -aq --filter "name=sandbox-") 2>/dev/null || true

# 启动后端
echo -e "${YELLOW}启动后端 (端口 8585)...${NC}"
cd "$PROJECT_DIR/backend"
uv run python server.py --port 8585 &
BACKEND_PID=$!

# 等待后端就绪
echo -e "${YELLOW}等待后端就绪...${NC}"
for i in $(seq 1 60); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo -e "${YELLOW}后端进程已退出，启动失败${NC}"
        cleanup
    fi
    if curl -sf "http://localhost:8585/docs" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ 后端已就绪${NC}"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo -e "${YELLOW}等待后端超时，仍继续启动前端${NC}"
    fi
    sleep 1
done

# 启动前端
echo -e "${YELLOW}启动前端 (端口 3585)...${NC}"
cd "$PROJECT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  服务已就绪${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}后端 PID: $BACKEND_PID${NC}"
echo -e "${GREEN}前端 PID: $FRONTEND_PID${NC}"
echo -e "${GREEN}前端地址: http://localhost:3585${NC}"
echo -e "${GREEN}后端地址: http://localhost:8585${NC}"
echo -e "${GREEN}API 文档: http://localhost:8585/docs${NC}"
echo ""
echo -e "${YELLOW}按 Ctrl+C 关闭所有服务${NC}"

wait
