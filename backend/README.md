# 学术论文研究智能体后端服务

基于 Google ADK + FastAPI + SSE 流式聊天的学术论文研究助手。

## 项目结构

```
backend/
├── app/
│   ├── agent.py           # Agent 配置（工具注册、skill 加载）
│   ├── tools.py           # 自定义工具（clarify, terminal, vision_analyze 等）
│   ├── narrator.py        # 旁路解说者（工具执行解说卡片）
│   ├── narrator_rules.py  # 解说规则/模板
│   ├── sandbox.py         # 沙箱管理器（预热池、文件同步）
│   ├── create_model.py    # 模型初始化（支持 10+ 供应商）
│   ├── file_reader.py     # 文件读取（PDF、PPT 等）
│   ├── instruction.md     # Agent 系统提示词
│   └── skills/            # 技能（arxiv-paper-search, bingsearch）
├── server.py              # FastAPI 服务（SSE 流式聊天）
├── client.py              # 命令行测试客户端
├── logs/                  # 对话日志
├── cache/                 # SSE 响应缓存
├── uploads/               # 用户上传文件
├── tests/
├── .env                   # 环境变量
├── env_example            # 环境变量模板
└── pyproject.toml
```

## 快速开始

### 1. 配置环境变量

```powershell
cd backend
copy env_example .env
```

编辑 `.env`，至少填写 `MODEL_PROVIDER` 和对应的 API Key。

### 2. 安装依赖

```powershell
cd backend
uv sync
# 或: pip install -e .
# 沙箱依赖: uv pip install -e ".[sandbox]"
```

### 3. 启动服务

```powershell
uv run python server.py
# 默认端口 8585，可用 --port 指定：uv run python server.py --port 8000
```

访问 `http://localhost:8585/docs` 查看 API 文档。

## 沙箱镜像构建

### 1. 构建镜像

```powershell
docker pull python:3.12

cd ..\sandbox-image
docker build -t my-sandbox:latest .
```

镜像基于 `python:3.12`，apt 源使用阿里云镜像，pip 源使用清华镜像。技能脚本预装在 `/app/skills/` 下。

### 2. 修改 .env

```ini
SANDBOX_ENABLED=true
SANDBOX_IMAGE=my-sandbox:latest
SANDBOX_POOL_SIZE=1
SANDBOX_DOMAIN=localhost:8080
SANDBOX_PROTOCOL=http
SANDBOX_API_KEY=123456
SANDBOX_TIMEOUT_MINUTES=30
SANDBOX_IDLE_MINUTES=15
```

### 3. 启动 OpenSandbox

```powershell
# 安装
uv tool install opensandbox

# 启动
uvx opensandbox-server
```

### 4. 启动后端（沙箱模式）

```powershell
uv run python server.py
# 默认端口 8585，可用 --port 指定
```

## API

### GET /chat/stream

SSE 流式聊天接口。

| 参数 | 说明 |
|------|------|
| `session_id` | 会话 ID（可选，不传自动生成） |
| `user_id` | 用户 ID |
| `message` | 用户消息 |

事件类型：

| 事件 | 说明 |
|------|------|
| `text` | 正文增量（打字机效果） |
| `thought` | 思考过程 |
| `tool_step` | 工具调用步骤（含子调用列表） |
| `tool_call` | 单次工具调用结束（status: running/done/error） |
| `clarify` | 人在回路澄清提问 |
| `narrator_card` | 解说卡片 |
| `done` | 流结束汇总 |

### POST /chat/answer

人在回路回答提交（clarify 环节使用）。

## 支持的模型供应商

DeepSeek、Claude、Gemini、OpenAI、阿里百炼、硅基流动、魔搭、豆包、vLLM、Ollama、本地 OpenAI 兼容接口。
