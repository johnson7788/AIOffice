# 管理服务文件说明

管理端用于优化主智能体 backend 的 Agent 配置和 Skills，通过分析 `backend/logs` 的会话日志驱动持续改进。

- **manage_backend**: FastAPI 服务，端口 `8686`，读写主 backend 的 `agent.py`、`skills/`、`logs/`
- **manage_frontend**: Vite + React 管理界面，端口 `3686`，通过 `/api` 代理到管理后端

---

## manage_backend

```
manage_backend
|-- .gitignore                    # 忽略 __pycache__, .venv, data/, .env
|-- app
|   |-- __init__.py               # 包初始化
|   |-- agent_manager.py          # Agent 配置管理（读写 instruction/description + 版本控制）
|   |-- config.py                 # 路径配置（指向 ../backend/app、skills、logs 目录）
|   |-- log_analyzer.py           # JSONL 日志解析器（聚合统计 + 优化提示生成）
|   |-- optimizer.py              # LLM 驱动优化器（调用 DeepSeek 生成优化建议）
|   `-- skill_manager.py          # Skill CRUD（创建/编辑/删除 SKILL.md + scripts + 版本备份）
|-- env_example                   # 环境变量模板（DEEPSEEK_API_KEY, MODEL）
|-- pyproject.toml                # Python 项目配置（FastAPI, litellm, watchdog 等依赖）
|-- server.py                     # FastAPI 主服务入口（16 个 API 端点）
`-- uv.lock                       # uv 包管理器锁文件
```

### 文件详解

| 文件 | 行数 | 功能说明 |
|------|------|---------|
| `server.py` | ~260 | FastAPI 主服务。定义 Agent/Skills/Logs/Optimize 四组 REST API，包含 CORS、Pydantic 请求模型、健康检查端点 |
| `app/config.py` | ~25 | 路径常量。`PROJECT_ROOT`→项目根目录，`BACKEND_DIR`→主 backend，`SKILLS_DIR`/`LOGS_DIR`→对应子目录，`MANAGE_DATA_DIR`→管理端自身数据（版本历史） |
| `app/agent_manager.py` | ~170 | **Agent 配置读写**。用正则从 `agent.py` 提取 instruction/description/name/model；更新时自动保存旧版本到 `data/agent_versions/`；支持 `rollback(version_id)` 回滚 |
| `app/skill_manager.py` | ~280 | **Skill 全生命周期管理**。列出所有 skills（解析 SKILL.md frontmatter + _meta.json）；创建新 skill（生成 SKILL.md 模板 + scripts 目录）；更新 SKILL.md 或脚本（自动版本备份）；删除（备份到 `data/skill_versions/`） |
| `app/log_analyzer.py` | ~240 | **日志分析**。列出 `backend/logs/*.jsonl`；解析单个日志（按事件类型分组、提取工具调用摘要、拼接回复文本）；全局聚合分析（工具使用分布、失败率、重复错误、生成优化提示） |
| `app/optimizer.py` | ~110 | **LLM 优化建议**。收集日志分析结果 + 当前 instruction + skills 列表，构建分析 prompt 调用 DeepSeek，返回三类建议：instruction_suggestions、skill_suggestions、new_skill_ideas |

### API 端点一览

```
Agent 配置
  GET    /api/agent                    获取当前 agent 配置
  PUT    /api/agent/instruction        更新 instruction
  PUT    /api/agent/description        更新 description
  GET    /api/agent/versions           列出历史版本
  GET    /api/agent/versions/{id}      获取指定版本详情
  POST   /api/agent/rollback           回滚到指定版本

Skill 管理
  GET    /api/skills                   列出所有 skills
  GET    /api/skills/{slug}            获取 skill 详情（SKILL.md + scripts 内容）
  POST   /api/skills                   创建新 skill
  DELETE /api/skills/{slug}            删除 skill（自动备份）
  PUT    /api/skills/{slug}/md         更新 SKILL.md
  GET    /api/skills/{slug}/scripts/{name}    获取脚本内容
  PUT    /api/skills/{slug}/scripts/{name}    更新脚本
  POST   /api/skills/{slug}/scripts          新建脚本
  GET    /api/skills/{slug}/versions         列出 skill 版本

日志分析
  GET    /api/logs                     列出日志文件
  GET    /api/logs/{filename}          获取日志详情
  GET    /api/logs/analyze             全局聚合分析
  GET    /api/logs/analyze/{filename}  分析单个日志

智能优化
  POST   /api/optimize/suggestions     LLM 生成优化建议

系统
  GET    /health                       健康检查
  GET    /api/status                   管理端状态（路径信息、统计）
```

---

## manage_frontend

```
manage_frontend
|-- .gitignore                        # 忽略 node_modules, dist, .env
|-- index.html                        # HTML 入口（标题：arXiv 研究助手 智能体管理后台）
|-- package-lock.json                 # npm 锁文件
|-- package.json                      # 项目依赖（React 19, react-router-dom, lucide-react, Tailwind CSS 4）
|-- src
|   |-- api.ts                        # API 客户端（完整的类型定义 + 请求封装）
|   |-- App.tsx                       # 路由配置（react-router-dom, 5 个页面路由）
|   |-- components
|   |   `-- Layout.tsx                # 侧边栏导航布局（Agent/Skills/Logs/Optimize 四个入口）
|   |-- index.css                     # 全局样式（Tailwind + 代码编辑器 + Markdown 渲染 + 滚动条）
|   |-- main.tsx                      # React 入口（StrictMode + createRoot）
|   `-- pages
|       |-- AgentPage.tsx             # Agent 配置编辑页（instruction 编辑器 + 版本历史 + 回滚）
|       |-- LogsPage.tsx              # 日志分析页（列表/详情/全局分析仪表盘三视图）
|       |-- OptimizePage.tsx          # 智能优化页（一键 LLM 分析 → 三类建议卡片展示）
|       |-- SkillDetailPage.tsx       # Skill 详情页（SKILL.md 编辑/预览 + 脚本编辑器）
|       `-- SkillsPage.tsx            # Skill 列表页（卡片列表 + 新建/删除对话框）
|-- tsconfig.json                     # TypeScript 配置（ES2022, strict, React JSX）
`-- vite.config.ts                    # Vite 配置（端口 3686, /api 代理到 :8686）
```

### 页面功能

| 页面 | 路由 | 功能 |
|------|------|------|
| **AgentPage** | `/agent` | 显示 agent name/model；编辑 description（单行输入）；编辑 instruction（多行代码编辑器，支持字符计数）；查看版本历史弹窗，一键回滚 |
| **SkillsPage** | `/skills` | 卡片式列出所有 skills（名称、描述、脚本数、测试数、SKILL.md 大小、修改时间）；新建 skill 对话框（slug/name/description）；删除（自动备份确认） |
| **SkillDetailPage** | `/skills/:slug` | Tab 切换：SKILL.md（编辑/预览 Markdown）和 Scripts（左侧脚本列表 + 右侧代码编辑器）；新建脚本；保存自动版本备份 |
| **LogsPage** | `/logs` | 三视图切换：**列表**（日期/时间、session_id、事件数、耗时、用户提问摘要）→ **详情**（事件统计、工具调用记录、错误记录、回复内容预览）→ **全局分析**（统计卡片、工具使用柱状图、优化提示、用户提问样例） |
| **OptimizePage** | `/optimize` | 一键触发 LLM 分析（调用 DeepSeek，约 15-30 秒）；展示三类建议卡片：Instruction 优化建议、Skill 优化建议、新 Skill 创意（含优先级标签） |

### 依赖说明

| 包 | 版本 | 用途 |
|---|------|------|
| `react` + `react-dom` | ^19.0.1 | UI 框架 |
| `react-router-dom` | ^7.6.1 | 页面路由 |
| `react-markdown` + `remark-gfm` | ^10 / ^4 | Markdown 渲染（SKILL.md 预览） |
| `lucide-react` | ^0.546.0 | 图标库 |
| `@tailwindcss/vite` | ^4.1.14 | Tailwind CSS v4 样式 |
| `vite` | ^6.4.3 | 构建工具 |
| `typescript` | ~5.8.2 | 类型检查 |

---

## 数据流

```
用户在管理前端操作
        │
        ▼
manage_frontend (:3686)  ──REST──▶  manage_backend (:8686)
                                           │
                              ┌────────────┼────────────┐
                              ▼            ▼            ▼
                      backend/app/   backend/app/   backend/logs/
                       agent.py       skills/*/       *.jsonl
                              │            │
                              ▼            ▼
                    修改后重启主 backend 即可生效
                    (每次修改自动保存版本，支持回滚)
```

## 启动

```bash
# 安装依赖（首次）
cd manage_backend && uv sync
cd manage_frontend && npm install

# 启动管理服务
cd manage_backend && uv run python server.py --port 8686 &
cd manage_frontend && npm run dev &

# 或同时启动全部 4 个服务
./start.sh
```

- 管理前端: http://localhost:3686
- 管理后端 API 文档: http://localhost:8686/docs
