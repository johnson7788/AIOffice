#!/bin/bash
# 生产部署：用 docker compose 构建并启动完整栈
# (nginx 静态 SPA + API 反代 → FastAPI 后端 + Postgres + MinIO)。
# 开发调试请用 ./start.sh。

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  部署 AIOffice (docker compose)${NC}"
echo -e "${GREEN}========================================${NC}"

# docker / compose 检查
command -v docker >/dev/null 2>&1 || { echo -e "${RED}未找到 docker${NC}"; exit 1; }
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    echo -e "${RED}未找到 docker compose${NC}"; exit 1
fi

# .env（compose 的 backend 服务 env_file 依赖它）
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo -e "${YELLOW}已从 .env.example 生成 .env —— 请填入模型 API Key 和 JWT_SECRET 后重新运行${NC}"
        exit 1
    fi
    echo -e "${RED}缺少 .env${NC}"; exit 1
fi

# 构建并启动
echo -e "${YELLOW}构建镜像并启动容器 (${COMPOSE} up --build -d)...${NC}"
$COMPOSE up --build -d

# 等待 nginx 前端 (:80) 与后端健康检查 (经 nginx 反代 /healthz)
echo -e "${YELLOW}等待服务就绪...${NC}"
for i in $(seq 1 60); do
    if curl -sf "http://localhost/healthz" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ 服务已就绪${NC}"; break
    fi
    [ "$i" -eq 60 ] && echo -e "${YELLOW}健康检查超时，请用 '${COMPOSE} logs' 查看${NC}"
    sleep 2
done

echo ""
$COMPOSE ps
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  部署完成${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}访问地址:  http://localhost/            (文档主入口)${NC}"
echo -e "${GREEN}           http://localhost/slides/     ${NC}"
echo -e "${GREEN}           http://localhost/pdf/        ${NC}"
echo -e "${GREEN}           http://localhost/markdown/   ${NC}"
echo -e "${GREEN}MinIO 控制台: http://localhost:9001    ${NC}"
echo ""
echo -e "${YELLOW}查看日志: ${COMPOSE} logs -f${NC}"
echo -e "${YELLOW}停止服务: ${COMPOSE} down${NC}"
