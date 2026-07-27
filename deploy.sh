#!/usr/bin/env bash
set -e

#######################################
#           参数与变量定义
#######################################
WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE=".env"
BRANCH_NAME="${BRANCH_NAME:-work}"
COMPOSE_FILE="docker-compose.yml"
CONTAINER_NAME="arxiv-research-agent"
PORT="${PORT:-8046}"

# ANSI color
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
  echo -e "${GREEN}======== [ $1 ] ========${NC}"
}

warn() {
  echo -e "${YELLOW}[WARN] $1${NC}"
}

err() {
  echo -e "${RED}[ERROR] $1${NC}"
}

#######################################
#           步骤 0：环境检查
#######################################
check_env() {
  log "Step 0: 环境检查"

  if ! command -v docker &>/dev/null; then
    err "Docker 未安装，请先安装 Docker"
    exit 1
  fi

  if ! docker compose version &>/dev/null; then
    err "Docker Compose 未安装，请先安装 Docker Compose"
    exit 1
  fi

  if [ ! -f "$WORK_DIR/$ENV_FILE" ]; then
    err "缺少 $ENV_FILE 文件，请创建并配置环境变量"
    echo ""
    echo "示例 $ENV_FILE 内容:"
    echo "  DEEPSEEK_API_KEY=sk-your-api-key"
    echo "  DEEPSEEK_BASE_URL=https://api.deepseek.com/v1"
    echo "  DEEPSEEK_MODEL=deepseek-v4-pro"
    echo "  PORT=8000"
    exit 1
  fi

  echo "环境检查通过"
}

#######################################
#           步骤 1：更新代码
#######################################
update_code() {
  log "Step 1: 拉取最新代码"
  cd "$WORK_DIR"

  if [ ! -d ".git" ]; then
    warn "非 Git 仓库，跳过代码更新"
    return
  fi

  git fetch origin
  git checkout "$BRANCH_NAME" || { err "切换分支 $BRANCH_NAME 失败"; exit 1; }
  git reset --hard "origin/$BRANCH_NAME"
  echo "当前分支: $(git branch --show-current)"
  echo "最新提交: $(git log -1 --oneline)"
}

#######################################
#           步骤 2：构建并启动容器
#######################################
restart_service() {
  log "Step 2: 构建并启动容器"

  cd "$WORK_DIR"
  docker compose -f "$COMPOSE_FILE" down --remove-orphans || true
  docker compose -f "$COMPOSE_FILE" up --build -d

  echo "等待服务启动..."
  sleep 3
}

#######################################
#           步骤 3：健康检查
#######################################
health_check() {
  log "Step 3: 健康检查"

  local max_retries=10
  local retry=0

  while [ $retry -lt $max_retries ]; do
    if curl -sf "http://localhost:$PORT/health" > /dev/null 2>&1; then
      echo "服务健康检查通过: http://localhost:$PORT/health"
      return 0
    fi
    retry=$((retry + 1))
    echo "等待服务就绪... ($retry/$max_retries)"
    sleep 2
  done

  err "健康检查失败，请查看容器日志: docker logs $CONTAINER_NAME"
  exit 1
}

#######################################
#           步骤 4：查看状态
#######################################
show_status() {
  log "Step 4: 服务状态"
  docker ps --filter "name=$CONTAINER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
  echo ""
  echo "API 接口:"
  echo "  健康检查: http://localhost:$PORT/health"
  echo "  研究接口: POST http://localhost:$PORT/research"
}

#######################################
#           主执行流程
#######################################
main() {
  check_env
  update_code
  restart_service
  health_check
  show_status
  log "部署完成!"
}

main "$@"
