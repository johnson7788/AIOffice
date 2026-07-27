# 在线办公 + Skills 智能体

一个把**对话式智能体**与**在线办公工作台**合到一起的应用：左边是能查论文、搜网页、生成 PPT、读文件的多技能 Agent，右边是一个「工作台」——文件树 + **ONLYOFFICE 在线编辑 doc/xls/ppt/pdf** + **Excalidraw 白板/思维导图**。智能体产出的文档（PPT、Markdown、CSV、思维导图……）直接落进工作台，点开即可在浏览器里二次编辑；更进一步，**你可以一边开着 PPT/文档，一边在侧栏用一句话让 AI 直接改它**——「把第一页背景改成红色」「把全文的『方案 A』替换成『方案 B』」，改动**实时落到你正在编辑的那份文档里**，所见即所得。这就是 **Online AI Office**。

**三条主线：**

- **Skills 智能体**（基于 Google ADK + DeepSeek）：图片型 PPT 生成（12 种预设风格）、可编辑型 PPT、arXiv 论文检索、网页搜索、文件上传问答，内置任务规划、终端/代码执行、图片分析（OCR）、人在回路澄清；通过**旁路解说架构**把工具调用与思考翻译成通俗中文卡片。
- **在线办公工作台**：每个用户一个文档空间（`backend/uploads/<user_id>/`），文件树浏览 + 预览，`.docx/.xlsx/.pptx/.pdf` 走 ONLYOFFICE 在线编辑（文字可选中可改），`.excalidraw` 走白板，Agent 产物用 `save_to_workspace` 落地成可编辑文件。
- **Online AI Office（对话式改文档）**：侧栏对话直接驱动 ONLYOFFICE。你说「改背景 / 替换文字」→ Agent 调 `enqueue_office_op` 生成一个受限结构化编辑指令 → 后端信箱 → 编辑器里常驻的后台插件轮询取走，用 ONLYOFFICE Builder API（`callCommand`）落到 live 会话——**不重写文件、不刷新页面、改动即时可见**。社区版免费，无需付费 Connector。

> 目录/集成设计见 [`plan.md`](plan.md)（P0 文件底座 → P1 Excalidraw → P2 ONLYOFFICE → P3 Skills 联动，均已实现并端到端验证）。

---

## 功能概览

| 功能 | 说明 |
|------|------|
| **工作台文件空间** | 每个用户一个文档空间（本地 `uploads/<user_id>/`），文件树浏览 + 在线预览（图片/文本/Markdown 内联，其他类型下载），上传/新建/删除 |
| **ONLYOFFICE 在线编辑** | 在浏览器里编辑 `.docx/.xlsx/.pptx/.pdf`，文字可选中可改；后端做 JWT 网关（签发 config、DocServer 拉原件、保存回写沙箱），社区版容器免费 |
| **Online AI Office（对话式改文档）** | 一边开着文档，一边在侧栏用自然语言让 AI 直接改它：改 PPT 页背景色、全文查找替换、改写选中文本。经「后端信箱 + 编辑器后台插件轮询」的 broker 桥，用 ONLYOFFICE Builder API 落到 live 会话，**实时可见、不重写文件**；社区版免费无需付费 Connector |
| **Excalidraw 白板/思维导图** | 纯前端画板，读写 `.excalidraw`，防抖自动保存；思维导图/流程图用其自带的 mermaid→excalidraw 转换 |
| **产物落地（save_to_workspace）** | Agent 把 Markdown/CSV/JSON/HTML/SVG/思维导图(.md) 等文本交付物写进工作台，自动进文件树，点开即用对应编辑器改 |
| **图片型 PPT 生成** | 选风格 / 传模版 · 一句话生成整套演示 · 图片型 16:9 幻灯片；12 种预设风格（科研答辩、麦肯锡、党政红等），每页由 qwen-image 生成一整张视觉统一的图，组装为可下载的 `.pptx` |
| **可编辑型 PPT（dashi-ppt）** | 基于 12 套预置主题编排页面，导出**文字可编辑**的 PPTX/PDF，可在 PowerPoint 或工作台里继续改 |
| **arXiv 论文检索** | 接入 arXiv 公开 API，支持按相关性/最新提交并行检索、按分类/作者检索、自由检索表达式 |
| **网页搜索** | 自建 SearXNG 实例，支持通用/新闻/图片/视频搜索，自动重试与诊断 |
| **文件上传问答** | 支持 PDF、PPTX、PPT、TXT 文件上传，自动提取内容并带位置标记（`[第X页]`、`[幻灯片X]`）注入 LLM 上下文 |
| **任务规划（todo）** | 面对多步骤研究任务，Agent 先拆解出待办清单并逐步推进、实时更新进度 |
| **终端执行（terminal）** | 在服务器上执行 shell 命令，查看环境、运行脚本、读取文件 |
| **多租户沙箱隔离** | 启用后 terminal/code 命令在每个租户（`user_id`）独占的 OpenSandbox 沙箱中执行，文件/进程/已装包互不干扰；预热池 + 闲置回收 + TTL 兜底 |
| **代码执行（code）** | 内置 Python 代码执行器，自动编写并运行代码做数据统计与计算，过程同样以解说卡片展示 |
| **图片分析 / OCR（vision）** | 上传截图、图表、结果表、扫描件等图片，调用独立视觉模型理解内容或提取文字（DeepSeek 无视觉能力，单独配置 qwen-vl-max） |
| **人在回路澄清（clarify）** | 需求模糊或缺关键信息时，Agent 主动反问澄清，用户回答后无缝续接同一会话继续执行 |
| **旁路解说** | 工具调用和思考过程被翻译为友好的中文卡片，实时推送给前端 |
| **SSE 流式输出** | 6 种事件类型实时推送，前端逐字打字机效果展示 |
| **SSE 响应缓存** | 相同问题秒级回放缓存结果（持久化到 `cache/` 目录，TTL 24h、LRU 淘汰） |
| **会话日志** | 每轮对话完整记录到 JSONL 文件，含事件历史、耗时、元数据 |
| **管理端** | 独立管理面板：Agent 配置编辑与版本回滚、技能管理、日志分析、LLM 智能优化建议 |

---

## 效果演示

![Agent 输出示例](docs/Agent输出示例.gif)

> 以下为示例查询，展示智能体的完整工作流程。

**查询**：对比 RAG 与长上下文窗口在知识密集型任务上的优劣

### 思考过程（旁路解说翻译后）

```
🧠 根据研究问题制定检索策略
🧠 分析主要实验结果与评测指标
```

### 工具调用过程（解说卡片）

```
[1]  📖 加载技能指导 …
       读取论文检索技能的详细分步指导

[2]  📖 加载技能指导 - 完成 ✓
       返回结构化数据，包含 3 个字段: skill_name, instructions, frontmatter

[3]  🔧 执行检索脚本 …
       正在执行 run_skill_script

[4]  🔧 执行检索脚本 …
       正在执行 run_skill_script

[5]  🔧 执行检索脚本 - 完成 ✓
       脚本执行成功，stdout 输出 28,114 字符

[6]  🔧 执行检索脚本 - 完成 ✓
       脚本执行成功，stdout 输出 31,902 字符
```

### 检索策略（智能体自动制定）

| 检索维度 | 工具 | 检索内容 |
|----------|------|----------|
| 综合论文 | arxiv-paper-search (all) | retrieval augmented generation + long context |
| 最新进展 | arxiv-paper-search (recent) | long context language model |
| 代码/解读 | searxng (general) | RAG vs long context window benchmark |

### 回答正文（节选）

> #### 两种范式的核心差异
>
> **RAG（检索增强生成）** 在推理时从外部知识库检索相关片段拼接到提示中，知识可随时更新、单次上下文成本低；**长上下文窗口** 则将全部材料直接放入模型上下文，省去检索环节、保留完整篇章结构 [1][2]。
>
> #### 在知识密集型任务上的对比
>
> | 维度 | RAG | 长上下文窗口 |
> |------|-----|-------------|
> | 知识更新 | 实时，无需重训 | 受窗口与训练数据限制 |
> | 推理成本 | 低（只注入相关片段） | 高（随长度平方增长） |
> | 长程依赖 | 受检索召回影响 | 完整保留篇章结构 |
> | 典型失败模式 | 检索召回不全 | lost in the middle |

**流结束统计**：正文约 6,000 字符 · 2 个工具步骤 · 6 张解说卡片

---

## 架构设计

```
用户提问
    │
    ▼
┌──────────────────────────────────────────────────────┐
│                  主 Agent (DeepSeek)                   │
│     （arXiv 论文检索、网页搜索、文件分析、深度思考）          │
└──────────┬──────────────┬──────────────┬─────────────┘
           │              │              │
     ┌─────▼─────┐  ┌────▼─────┐  ┌─────▼─────┐
     │ 正文回复   │  │ 思考过程  │  │ 工具调用   │
     │ (text)    │  │(thought) │  │(tool_step)│
     └─────┬─────┘  └────┬─────┘  └─────┬─────┘
           │              │              │
           │        ┌─────▼─────┐  ┌─────▼──────┐
           │        │ 旁路解说   │  │ 旁路解说    │
           │        │ 翻译思考   │  │ 翻译工具    │
           │        └─────┬─────┘  └─────┬──────┘
           │              │              │
           ▼              ▼              ▼
     ┌─────────┐  ┌────────────┐  ┌────────────┐
     │ 最终答案 │  │ 🧠 思考卡片 │  │ 🔬 工具卡片 │
     │ 流式展示 │  │ 通俗中文    │  │ 友好标签    │
     │ 给用户   │  │ 解说       │  │ 进度展示    │
     └─────────┘  └────────────┘  └────────────┘
           │              │              │
           └──────────────┼──────────────┘
                          ▼
                   SSE 流式推送 → React 前端
```

### 旁路解说：三个回调钩子

| 回调 | 触发时机 | 作用 |
|------|---------|------|
| `before_tool_callback` | 工具执行前 | 告诉用户"即将做什么"（`status: "running"`） |
| `after_tool_callback` | 工具执行后 | 告诉用户"做了什么，结果如何"（`status: "done"`） |
| `after_model_callback` | LLM 每次响应后 | 将思考过程翻译为通俗说明 |

**设计原则**：解说只翻译过程，绝不触碰正文输出；解说失败静默捕获，绝不影响主 Agent。

---

## 在线办公工作台

前端分「对话」和「工作台」两个页签，共享同一个 `user_id`。工作台把该用户的文档空间当网盘根目录，按文件后缀路由到不同编辑器。

```
┌── 前端 (Vite:3585) ─────────────────────────────┐
│  对话页签 (App.tsx)   │   工作台页签 (Workspace.tsx) │
│  聊天/SSE            │   文件树 │ 预览/编辑区         │
└──────┬───────────────────────┬────────────────────┘
       │ SSE                    │ REST 文件API / 编辑器 config
       ▼                        ▼
┌── 后端 FastAPI (8585) ──────────────────────────┐
│  /chat/stream   /files/*   /office/*(网关+JWT)  │
└──────┬───────────────────────┬───────────────────┘
       │ 本地文件               │ HTTP 拉取/回写
       ▼                        ▼
  uploads/<user_id>/       ONLYOFFICE DocumentServer
  (文档真身在这)             (独立容器 :8081)
```

### 关键设计

- **文档空间 = 本地 `backend/uploads/<user_id>/`**，不是沙箱。`generate_ppt` 直接写本地、`/download` 也从本地读；沙箱只用于代码执行。dashi-ppt 在沙箱内导出 `.pptx/.pdf`，再由 `sync_sandbox_to_workspace` 拉回本地目录。文件树 / Excalidraw / ONLYOFFICE 都操作这个本地目录。
- **路径安全**：所有 `/files/*`、`/office/*` 端点按 `user_id` 定位目录，路径 `resolve()` + `startswith` 规范化，挡住 `../` 越权（`server.py:_safe_user_path`）。

### ONLYOFFICE 网关（doc/xls/ppt/pdf）

DocumentServer 是独立容器，只认 HTTP URL，而文件在本地，所以后端当**文件网关**，全程 JWT（密钥 `OFFICE_JWT_SECRET` 只在后端）：

| 端点 | 作用 |
|------|------|
| `GET /office/config` | 读文件信息 → 返回**签名后**的 DocEditor config（含 `document.url`、`document.key`、`callbackUrl`、`token`） |
| `GET /office/download` | DocServer 来拉原件：验 JWT → 返回文件字节流 |
| `POST /office/callback` | DocServer 保存回调：`status∈{2,6}` 时下载编辑后文件 → 写回本地 uploads |

- `document.key = md5(user:path:mtime)`：同一版本稳定、内容变则变，否则编辑器显示缓存旧内容。
- 后缀 → documentType：`.docx→word`、`.xlsx→cell`、`.pptx→slide`、`.pdf→pdf`。
- DocServer 容器回访后端的地址用 `OFFICE_BACKEND_URL`（`host.docker.internal:8585`，**不能用 localhost**——那是容器自己）。
- 未配置 `OFFICE_JWT_SECRET` 时，前端 `OfficeEditor.tsx` 自动回退到「下载」。

### Online AI Office：对话式改 office 文档（broker 桥）

让**侧栏助手**能直接改**你正在编辑器里打开的那份文档**，是这个项目的核心特性。难点在于：ONLYOFFICE 编辑器跑在多层 iframe 里，社区版又没有把编辑器 API 暴露给宿主页的付费 **Connector**——侧栏（React 应用）没法跨 iframe 直接遥控编辑器。

**设计原则：编辑器是真相源，LLM 只产补丁，编辑器 API 负责落地，后端不碰 office 二进制。** 早期用后端 python-pptx 整文件重写的做法被弃用（脆：会被模板封面遮挡、无粒度、与 live 会话抢写还不刷新）。现在改走 ONLYOFFICE 插件的 `callCommand`（Builder API），在 live 会话里精确落点、所见即所得。

**方案 = broker（信箱中转）桥**——两边都只跟后端讲话，绕开跨 iframe：

```
侧栏对话「把第一页背景改成红色」
    │
    ▼  Agent 判断是 office 编辑，调用 enqueue_office_op
enqueue_office_op(op_type=set_slide_background, slide=0, color=#FF0000)
    │  parse_office_op 校验（受限指令集）
    ▼
后端进程内信箱  _PENDING[user_id] ← op        （app/office_ops.py）
    │
    │   ┌───────────────────────────────────────────────┐
    │   │  编辑器里常驻的「AI 桥」后台插件 (ai-bridge)       │
    └──▶│  每 2s 轮询 GET /office/pending?user_id=...      │
        │  取走 op → callCommand 落到 live 会话           │  (poll.js)
        └───────────────────────────────────────────────┘
                              │
                              ▼
              editor live 会话背景变红（即时可见）
                              │
              Ctrl+S / 关闭 → forcesave → /office/callback → 写回磁盘
```

**受限结构化指令集**（不是任意 Builder JS，先保安全可控）——`app/office_ops.py:parse_office_op` 校验后才入信箱：

| op | 参数 | 作用 |
|----|------|------|
| `set_slide_background` | `slide`（0 起）、`color`（`#RRGGBB`） | 改某页 PPT 背景色 |
| `replace_text` | `find`、`replace` | 全文查找替换 |
| `replace_selection` | `text` | 用新文本替换当前选区（走可视插件面板） |

**两个插件，各司其职**（关键坑：ONLYOFFICE 的 `autostart` 与工具栏按钮**都启动 `variations[0]`**，一个插件没法既做后台轮询又做可视面板，必须拆开）：

- **`ai-bridge`**（后台常驻，`isSystem`）：`background.html` + `poll.js`，靠 `/office/config` 里的 `editorConfig.plugins.autostart` 在开编辑器时自动起轮询。这是 broker 桥的取件端。
- **`ai-rewrite`**（可视面板）：用户手动点开，读选区文本 → 发后端/LLM 改写 → `PasteText` 写回选区。对应上面的 `replace_selection`。

**关键端点/文件：**

| 位置 | 作用 |
|------|------|
| `app/tools.py: enqueue_office_op` | Agent 工具：把编辑意图转成一个校验过的 op 投进信箱 |
| `app/office_ops.py` | `parse_office_op`（校验）+ `_PENDING` 信箱（`enqueue_op` / `drain_ops`） |
| `GET /office/pending?user_id=` | 后台插件的取件口，返回并清空该用户的待办 op |
| `backend/office_plugin/ai-bridge/` | 后台轮询插件（`config.json` / `background.html` / `poll.js`） |
| `backend/office_plugin/ai-rewrite/` | 可视改写插件（选区级） |

**落地即时、落盘沿用 P2**：`callCommand` 只改 live 模型，用户即时看到变化；持久化到磁盘沿用 ONLYOFFICE 的 autosave / 关闭时 `forcesave` → `/office/callback` 写回 `uploads/<user_id>/`。

> ⚠️ 部署注意（两个已知坑）：
> 1. **插件资源的 `.gz`**：documentserver 的 nginx 开了 `gzip_static`，会**优先服务同名 `.gz`**。改完插件 `config.json/*.html/*.js` 必须重新生成 `.gz`（`gzip -kf ...`），否则浏览器拿到旧内容。
> 2. **浏览器缓存 service worker**：ONLYOFFICE 会缓存插件注册表。若在插件上线前打开过编辑器，普通刷新可能仍走旧缓存导致后台插件不启动——用**无痕窗口**或「清空缓存并硬性重新加载」即可（全新上下文＝插件正常 autostart）。

### Excalidraw 白板

纯前端组件 `WhiteboardEditor.tsx`：读 `.excalidraw`（`GET /files/raw`）→ `<Excalidraw initialData>` → onChange 防抖 800ms → 序列化写回（`PUT /files/raw`）。思维导图/流程图用 Excalidraw 自带的 mermaid→excalidraw，Agent 直接产 mermaid 即可。

### 与 Skills 的联动

- **正向**：Agent 用 `save_to_workspace`（文本产物）、`generate_ppt`（图片型 PPT）或 `sync_sandbox_to_workspace`（把 dashi-ppt 在沙箱导出的 `.pptx/.pdf` 拉回）把文件写进 uploads → 文件树出现 → 点开即用对应编辑器改。
- **反向**：编辑器里改完存回 uploads → 用户可让 Agent「基于我刚改的 X.pptx 继续…」，Agent 读同一份文件。

---

## 智能体能力（工具）

除四个技能（arXiv 论文检索、网页搜索、图片型 PPT `ppt-deck`、可编辑型 PPT `dashi-ppt`）外，Agent 还内置以下通用工具，定义在 `backend/app/tools.py`，并在 `backend/app/agent.py` 中注册：

| 工具 | 类型 | 说明 |
|------|------|------|
| `generate_ppt` | PPT 生成 | 图片型 PPT：模型规划提纲并为每页写出图提示词 → qwen-image 逐页出图 → python-pptx 组装 16:9 `.pptx`，返回下载链接。支持 12 种预设风格（科研答辩风、麦肯锡风格、党政红等） |
| `save_to_workspace` | 产物落地 | 把文本交付物（Markdown/CSV/JSON/HTML/SVG/思维导图 .md）写进工作台 `uploads/<user_id>/`，自动进文件树可编辑（5MB 上限，`../` 越权拦截） |
| `sync_sandbox_to_workspace` | 沙箱→工作台 | 把沙箱内生成的二进制产物（如 dashi-ppt 导出的 `.pptx/.pdf`）拉回本地 `uploads/<user_id>/`，返回下载链接（50MB 上限，`../` 越权拦截） |
| `sync_upload_to_sandbox` | 工作台→沙箱 | 把用户已上传的文件同步进沙箱，供 `terminal` 在沙箱内处理 |
| `enqueue_office_op` | 对话式改文档 | Online AI Office：把「改 PPT 背景 / 全文替换 / 改写选区」转成受限结构化 op，校验后投进后端信箱，由编辑器后台插件轮询取走并用 Builder API 落到 live 会话（严禁用 python-pptx 重写文件） |
| `todo` | 任务规划 | 拆解复杂任务为待办清单并跟踪进度，状态存于会话 state（单轮会话内有效） |
| `terminal` | 终端执行 | `subprocess` 执行 shell 命令，返回 stdout/stderr/returncode（高权限，请在受信部署边界内使用） |
| `execute_code` | 代码执行 | Google ADK 内置 `UnsafeLocalCodeExecutor`，自动编写并运行 Python 代码处理数据/计算 |
| `vision_analyze` | 图片分析/OCR | 通过独立视觉模型（默认 qwen-vl-max）分析图片或提取文字，支持图片 URL 或已上传文件名 |
| `clarify` | 人在回路 | `LongRunningFunctionTool`，向用户提问澄清后挂起，等待回答再续接同一会话 |

### 人在回路（clarify）工作流

```
用户提问（模糊）
    │
    ▼  Agent 判断需求不明确，调用 clarify
SSE 事件 clarify {session_id, call_id, question, choices[]}
    │
    ▼  前端渲染澄清卡片（问题 + 选项按钮 + 自由输入）
用户回答
    │
    ▼  POST /chat/answer  以 function_response 回灌同一 session_id
SSE 续接（text / thought / tool_step ... / done），无缝继续执行
```

> 实现要点：`/chat/stream` 与 `/chat/answer` 共用核心流式 helper `_run_agent_stream(...)`；
> 由于澄清回答无法被缓存回放，clarify 触发的会话**跳过 SSE 缓存**。

### 演示示例

前端欢迎页内置了覆盖各项能力的示例问题，点击即可体验（带文件的示例会自动上传内置 demo 文件）：

| 示例问题 | 演示能力 |
|----------|---------|
| 把大语言模型的发展脉络做成一套 12 页 PPT | generate_ppt（图片型 PPT 生成） |
| 生成一份「MoE 架构」的教学幻灯片 | generate_ppt + arXiv 检索 |
| 根据这份讲义生成一套演示文稿 | generate_ppt + 文件上传（自动上传 demo PPT） |
| 帮我对比一下**这两个方向**的代表性工作，给出选型建议 | clarify（未指明对象 → 反问澄清） |
| 系统调研扩散语言模型的发展脉络，分阶段梳理并形成综述 | todo（多步任务规划） |
| 识别这张基准测试结果表中的数据，并补充该评测的代表性论文 | vision/OCR（自动上传图片） |

---

## PPT 生成

核心 PPT 生成流程：LLM 规划提纲 → 为每页写一段出图提示词 → 调用阿里 DashScope `qwen-image` 异步 API 逐页渲染 16:9 整图 → `python-pptx` 组装为 `.pptx`（含演讲备注）→ 返回下载链接。

### 预设风格（12 种）

科研答辩风、麦肯锡风格、清爽专业风、数据仪表盘风、党政红风格、教学课件风、温暖手工风、手绘白板风、手绘技术解释风、电子墨水杂志风、创意杂志风、复古扁平插画风。

前端提供下拉选择，选定后风格描述自动注入每页出图提示词。

### 工作流程

```
用户："做一套 LLM 发展史 PPT，麦肯锡风格"
    │
    ▼  Agent load_skill("ppt-deck") 获取分步指导
Agent 规划提纲，为每页写英文出图 prompt + 中文演讲备注
    │
    ▼  Agent 调用 generate_ppt(slides=[...], style="麦肯锡风格")
后端线程：逐页调用 qwen-image 异步出图（每页约 30-60s）
    │
    ▼  python-pptx 组装 16:9 幻灯片（铺满整图 + 演讲备注）
返回 download_url → Agent 以 markdown 链接给用户下载
```

### 设计要点

- **出图在后端本地跑**，不进沙箱——沙箱镜像没有 `python-pptx`。（若确需沙箱产物落地，可用 `sync_sandbox_to_workspace` 拉回，dashi-ppt 走这条路）
- **qwen-image 无负向提示词**：写"不要浏览器"反而会把浏览器画出来，所以只写正向约束
- **页数上限 20 页**，避免生成时间过长

---

## 多租户沙箱隔离（OpenSandbox）

`terminal`、`execute_code` 默认在服务器本地执行。启用沙箱后，命令改在**每个租户（`user_id`）独占的隔离沙箱**中执行，文件、进程、已装包互不干扰。实现见 `backend/app/sandbox.py`：

- **预热池**：启动时预建 `SANDBOX_POOL_SIZE` 个空闲沙箱，首次使用即时 acquire，reconciler 自动补满
- **每租户独占 + 活跃续期**：同一 `user_id` 复用同一沙箱，活跃时自动续 TTL，避免长会话被硬杀
- **闲置回收 + TTL 兜底**：租户闲置 `SANDBOX_IDLE_MINUTES` 后回收；单沙箱硬性存活上限 `SANDBOX_TIMEOUT_MINUTES` 防泄漏
- **技能脚本同步**：`ensure_skills` 首次使用时把本地 skill 脚本写入沙箱
- **未启用零依赖**：`SANDBOX_ENABLED=false` 时回退本地 `subprocess`，不引入 OpenSandbox SDK，行为不变

### 启用步骤（自动化脚本）

三个脚本覆盖准备 → 启动沙箱服务端 → 启动应用，沙箱由后端连接池按每租户自动创建，无需手动 `osb sandbox create`：

```bash
# 1. 一次性环境准备（幂等，可重复运行）
#    检查 Docker → 拉取 opensandbox/execd 镜像 → 构建沙箱镜像 my-sandbox:latest
#    → 写入 ~/.sandbox.toml 服务端配置 → 配置 osb CLI 连接参数
./prepare.sh

# 2. 启动 OpenSandbox 服务端（保持运行，幂等——已在 :8080 运行则自动跳过）
./start_sandbox.sh

# 3. 在根目录 .env 中确认已开启（prepare 后默认即为下列值）
#    SANDBOX_ENABLED=true
#    SANDBOX_IMAGE=my-sandbox:latest

# 4. 启动应用（后端 :8585 + 前端 :3585），后端会自动向服务端创建每租户沙箱
./start.sh
```

> `prepare.sh` 只需在首次部署或更新沙箱镜像时运行；`start_sandbox.sh` 检测到服务端已在跑会直接跳过。
> 手动构建沙箱镜像：`docker build -t my-sandbox:latest ./sandbox-image`。

---

## 项目结构

```
skill-ppt-agents/
├── .env                          # 环境变量（API Key、端口等）
├── Dockerfile                    # 生产镜像（Python 3.12 + Node 20 + Gunicorn）
├── docker-compose.yml            # 容器编排（arxiv-agent + onlyoffice documentserver:8081）
├── sandbox-image/                # 沙箱镜像（python:3.12 + pandoc + 技能脚本预装）
├── prepare.sh                    # 一次性环境准备：检查 Docker、拉取 execd 镜像、构建沙箱镜像、写入 OpenSandbox 服务端配置与 CLI 配置
├── start_sandbox.sh              # 启动 OpenSandbox 服务端（:8080，幂等——已在运行则自动跳过）；沙箱由后端连接池按租户自动创建
├── start.sh                      # 本地开发启动：后端（:8585，uv run）+ 前端（:3585，npm run dev），Ctrl+C 统一关闭
├── deploy.sh                     # 生产部署（git pull → docker compose up → 健康检查）；基础版本，尚未详细优化
│
├── backend/
│   ├── pyproject.toml            # Python 依赖（hatchling 构建）
│   ├── server.py                 # FastAPI 服务端（SSE 流式、文件上传/下载、缓存、/files/* 文件树、/office/* ONLYOFFICE 网关）
│   ├── client.py                 # CLI 客户端（模拟前端，消费 SSE）
│   ├── office_plugin/            # Online AI Office 的 ONLYOFFICE 插件
│   │   ├── ai-bridge/            # 后台常驻插件：autostart 轮询 /office/pending → callCommand 落地（broker 桥）
│   │   └── ai-rewrite/           # 可视改写插件：读选区 → LLM 改写 → PasteText 写回
│   ├── app/
│   │   ├── agent.py              # Agent 定义（DeepSeek + 技能 + 工具 + 回调）
│   │   ├── tools.py             # 自定义工具：generate_ppt / save_to_workspace / enqueue_office_op / todo / terminal / vision_analyze / clarify
│   │   ├── office_ops.py         # Online AI Office：op 校验（parse_office_op）+ 进程内信箱（_PENDING / enqueue_op / drain_ops）
│   │   ├── sandbox.py           # 多租户沙箱隔离（OpenSandbox 预热池 + 每租户独占 + 闲置回收）
│   │   ├── create_model.py      # 模型工厂（10+ 供应商，统一走 LiteLLM）
│   │   ├── narrator.py           # 旁路解说回调逻辑（三回调 + 格式化）
│   │   ├── narrator_rules.py    # 解说规则：TOOL_LABELS 工具标签 + 思考翻译模式
│   │   ├── file_reader.py        # PDF/PPTX/PPT/TXT/图片 文件提取（带位置标记）
│   │   ├── instruction.md       # Agent 系统提示词（中文）
│   │   └── skills/
│   │       ├── arxiv-paper-search/       # arXiv 学术论文检索
│   │       ├── bingsearch/               # Bing 网页搜索
│   │       ├── ppt-deck/                # 图片型 PPT 生成（12 种预设风格）
│   │       └── dashi-ppt/               # 可编辑型 PPT（12 套主题，导出文字可编辑 PPTX/PDF）
│   ├── cache/                    # SSE 响应缓存（JSON 文件）
│   ├── logs/                     # 会话日志（JSONL）
│   └── uploads/                  # 用户上传文件 + 生成的 PPT
│
├── frontend/
│   ├── package.json              # Node 依赖
│   ├── vite.config.ts
│   ├── public/demo/             # 内置演示文件（PPT、基准结果表图片）
│   └── src/
│       ├── main.tsx              # Shell：对话/工作台 两个页签 + 共享 userId
│       ├── App.tsx               # 对话界面（时间线、工具卡片、思考卡片、澄清卡片、PPT 风格选择、Markdown）
│       ├── Workspace.tsx         # 工作台：文件树 + 预览 + 按后缀路由到编辑器（上传/新建白板/删除）
│       ├── WhiteboardEditor.tsx  # Excalidraw 白板（读写 .excalidraw，防抖保存）
│       ├── OfficeEditor.tsx      # ONLYOFFICE 编辑器（加载 api.js 嵌 DocEditor，未配置回退下载）
│       ├── api.ts                # SSE 客户端 + 文件 API（tree/raw/上传/删除）
│       └── index.css             # Tailwind + 自定义样式
│
├── manage_backend/               # 管理后端（FastAPI，端口 8686）
│   ├── server.py                 # 管理服务端（Agent 配置、技能管理、日志分析、智能优化）
│   ├── app/
│   │   └── config.py             # 路径配置（指向主 backend 的文件系统）
│   └── data/                     # 版本历史快照（agent_versions/、skill_versions/）
│
├── manage_frontend/              # 管理前端（React + Vite，端口 3686）
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx               # 路由 + 侧边栏布局
│       └── pages/
│           ├── AgentPage.tsx     # Agent 配置编辑 + 版本回滚
│           ├── SkillsPage.tsx    # 技能列表 + 新建/删除
│           ├── SkillDetailPage.tsx # 技能详情（SKILL.md 编辑 + 脚本管理）
│           ├── LogsPage.tsx      # 日志浏览 + 聚合分析
│           └── OptimizePage.tsx  # LLM 驱动的智能优化建议
│
├── test/                         # 集成测试（pytest + httpx）
│   ├── test_office_files.py     # 工作台文件 API + ONLYOFFICE 网关 + save_to_workspace（进程内 ASGI）
│   ├── test_specific_question.py # 论文问答 + 缓存测试
│   └── test_ppt_qa.py            # PPT 上传 + 幻灯片引用问答测试
│
└── docs/                         # 设计文档
```

---

## 快速开始

### 本地开发

```bash
# 1. 后端依赖
cd backend
uv sync

# 2. 前端依赖
cd ../frontend
npm install

# 3. 配置环境变量（单一根目录 .env）
cp env_example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 4. 一键启动（后端 :8585 + 前端 :3585）
./start.sh

```

### 启用在线编辑（ONLYOFFICE，可选）

不配也能用工作台（预览 + 白板 + 下载），只有 `.docx/.xlsx/.pptx/.pdf` 的**在线编辑**需要 DocumentServer 容器。

```bash
# 1. 在 .env 里配好共享密钥（后端与容器必须一致）
#    OFFICE_JWT_SECRET=<一段足够长的随机串>
#    OFFICE_PORT=8081
#    OFFICE_BACKEND_URL=http://host.docker.internal:8585   # 不是 localhost

# 2. 起 DocumentServer 容器（社区版，免费）
docker run -d --name onlyoffice-documentserver -p 8081:80 \
  -e JWT_ENABLED=true -e JWT_SECRET="$OFFICE_JWT_SECRET" \
  onlyoffice/documentserver
#   首次拉镜像 ~2GB；等 `curl -s localhost:8081/healthcheck` 返回 true 即就绪

# 3. 工作台里点开 .docx/.pptx 即可在线编辑，保存自动回写 uploads/<user_id>/
```

> compose 里也有 `documentserver` 服务，但 `docker compose up documentserver` 会插值整个
> compose 文件（arxiv 服务需要额外变量）；只验证在线编辑时直接用上面的 `docker run` 更省事。
> 端到端链路（容器拉原件 + 保存回写）已由 `test/test_office_files.py` 覆盖。

### CLI 客户端（无需前端）

```bash
cd backend
python client.py                              # 交互模式
python client.py "分析销售数据"                 # 自定义查询
python client.py --verbose "研究 AI 趋势"     # 显示原始思考（调试用）
```

### Docker 部署

```bash
# 配置 .env（DEEPSEEK_API_KEY 必填）
./deploy.sh    # 完整流程：环境检查 → git pull → docker compose up → 健康检查

# 或手动：
docker compose up --build -d    # 容器端口 8046
```

### 运行测试

```bash
cd test
pytest test_office_files.py -v              # 工作台文件 API + ONLYOFFICE 网关 + 落地（进程内 ASGI，无需起服务/Docker）
pytest test_ppt_qa.py -v                    # PPT 上传 + 问答测试（需后端已启动）
pytest test_specific_question.py -v         # 论文问答 + 缓存测试（需后端已启动）
TEST_SERVER_URL=http://host:port pytest . -v  # 对远程服务器测试
```

> `test_office_files.py` 直接把 FastAPI app 挂到 httpx ASGITransport 上跑，覆盖 P0 文件读写删 + `../` 越权、
> P2 网关 config 签发/download 验签/callback 写回、P3 `save_to_workspace`，15 个用例，无需 Docker 或运行中的服务。

---

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/chat/stream?message=...&user_id=...` | **SSE 流式对话** — 实时推送事件流 |
| `POST` | `/chat/answer` | **回答澄清提问** — 续接 clarify 人在回路（body: `session_id`/`call_id`/`answer`/`user_id`），以 SSE 续接同一会话 |
| `POST` | `/chat` | **非流式对话** — 返回完整 JSON |
| `POST` | `/upload` | **上传文件**（multipart: `file` + `user_id`） |
| `GET` | `/uploads?user_id=...` | **列出用户上传的文件** |
| `DELETE` | `/uploads?user_id=...` | **清理用户所有上传文件** |
| `GET` | `/download?user_id=...&file=...` | **下载产物文件**（如生成的 `.pptx`），仅限 `uploads/<user_id>/` 内 |
| `GET` | `/files/tree?user_id=...` | **工作台文件树**（递归列出用户文档空间） |
| `GET` | `/files/raw?user_id=...&path=...` | **读取单个文件**（Excalidraw 加载 / 预览 / office 下载共用） |
| `PUT` | `/files/raw` | **写入文本文件**（body: `path`/`content`/`user_id`；Excalidraw 保存、新建文件） |
| `DELETE` | `/files?user_id=...&path=...` | **删除文件或目录** |
| `GET` | `/office/config?user_id=...&path=...` | **签发 ONLYOFFICE DocEditor 配置**（JWT 签名，含 docserver 地址） |
| `GET` | `/office/download?token=...` | **DocServer 拉取原件**（验签 → 文件字节流） |
| `POST` | `/office/callback?token=...` | **DocServer 保存回调**（验签 → status 2/6 时写回沙箱） |
| `GET` | `/office/pending?user_id=...` | **Online AI Office 取件口** — 编辑器后台插件轮询，返回并清空该用户待落地的编辑 op |
| `GET` | `/cache/info` | **缓存统计信息** |
| `DELETE` | `/cache` | **清空 SSE 缓存** |
| `GET` | `/health` | **健康检查** |
| `GET` | `/docs` | **Swagger UI** |

---

## SSE 事件协议（v2）

| 事件类型 | 关键字段 | 用途 |
|---------|---------|------|
| `text` | `text` | 正文内容，前端逐字追加 |
| `thought` | `raw`, `narrated` | 思考卡片（可折叠，摘要显示 narrated） |
| `tool_step` | `step_id`, `summary`, `calls[]` | 新工具步骤卡片 |
| `tool_call` | `step_id`, `call_id`, `status`, `result_summary` | 更新子调用状态 |
| `narrator_card` | `card`, `card_index` | 旁路解说卡片 |
| `clarify` | `session_id`, `call_id`, `question`, `choices[]` | 人在回路澄清提问，前端渲染澄清卡片，回答经 `POST /chat/answer` 续接 |
| `done` | `text_len`, `thought_count`, `step_count`, `card_count` | 流结束统计 |

**事件示例：**

```json
{"type": "text", "text": "根据文献检索的结果..."}

{"type": "thought", "raw": "I need to search for recent papers...", "narrated": "正在检索相关方向的最新论文"}

{"type": "tool_step", "step_id": "s1", "summary": "🔬 检索学术论文", "calls": [{"call_id": "c1", "tool": "arxiv_search", "status": "running"}]}

{"type": "narrator_card", "card": {"phase": "before_tool", "tool": "arxiv_search", "icon": "🔬", "label": "检索学术论文", "detail": "通过 arXiv API 检索相关方向的论文", "status": "running"}, "card_index": 0}

{"type": "clarify", "session_id": "s-abc", "call_id": "c-123", "question": "你想对比哪两个方向？", "choices": ["RAG vs 长上下文", "MoE vs Dense"]}

{"type": "done", "text_len": 2340, "thought_count": 3, "step_count": 2, "card_count": 7}
```

---

## 前端

**技术栈：** React 19 + TypeScript + Vite 6 + Tailwind CSS 4

| 特性 | 说明 |
|------|------|
| **暗色主题** | `#0b0f19` 深色背景 |
| **实时流式** | SSE 打字机效果，逐字展示正文 |
| **工具步骤卡片** | 可折叠，展示子调用详情与状态 |
| **思考过程卡片** | 可折叠，摘要显示翻译后中文，展开查看原始思考 |
| **澄清卡片** | clarify 人在回路：渲染问题 + 选项按钮 + 自由输入，回答后续接同一会话 |
| **文件上传** | 拖拽 + 点击上传，支持 PDF/PPTX/PPT/TXT 及图片（OCR） |
| **PPT 模版风格** | 12 种预设风格下拉选择（科研答辩风、麦肯锡风格等），选中后自动注入生成指令 |
| **Markdown 渲染** | 表格、代码块、链接完整支持（react-markdown + remark-gfm） |
| **可中断** | 停止按钮，随时中止流式请求 |
| **动画** | Framer Motion (motion) 过渡动画 |

```bash
cd frontend
npm install
npm run dev        # 开发模式（HMR，自动代理到后端）
npm run build      # 生产构建 → dist/
```

---

## 管理端

独立的管理面板，提供 Agent 配置编辑、技能管理、日志分析和 LLM 驱动的智能优化建议。管理后端直接读写主 backend 的文件系统，修改后重启主服务即可生效。

![优化智能体界面](docs/优化智能体界面.png)

**技术栈：** React 19 + TypeScript + Tailwind CSS 4（前端）/ FastAPI + litellm（后端）

### 功能模块

| 模块 | 路径 | 说明 |
|------|------|------|
| **Agent 配置** | `/agent` | 在线编辑 Agent 的 `instruction` 和 `description`，支持版本历史和一键回滚 |
| **技能管理** | `/skills` | 查看、创建、删除技能；编辑 SKILL.md 指导文档和 Python 脚本，每次修改自动保存版本快照 |
| **日志分析** | `/logs` | 浏览 JSONL 会话日志，查看事件分布、工具调用记录和错误信息；全局聚合分析工具使用率和成功率 |
| **智能优化** | `/optimize` | 将日志分析结果和当前配置发送给 DeepSeek，生成指令优化建议、技能改进方案和新技能创意 |

### 架构特点

- **文件系统直连**：管理后端通过读写 `backend/app/agent.py`、`backend/app/skills/`、`backend/logs/` 操作主服务，无需 HTTP 中转
- **版本安全网**：每次编辑操作自动保存 JSON 快照到 `manage_backend/data/`，支持回滚到任意历史版本
- **无认证**：设计为内部开发/管理工具，CORS 全开放

### 管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/agent` | 读取当前 Agent 配置（名称、描述、指令、模型） |
| `PUT` | `/api/agent/instruction` | 更新 Agent 指令（自动保存版本） |
| `PUT` | `/api/agent/description` | 更新 Agent 描述（自动保存版本） |
| `GET` | `/api/agent/versions` | 列出 Agent 配置历史版本 |
| `POST` | `/api/agent/rollback` | 回滚到指定版本 |
| `GET` | `/api/skills` | 列出所有技能 |
| `GET` | `/api/skills/{slug}` | 获取技能详情（SKILL.md + 脚本内容） |
| `POST` | `/api/skills` | 创建新技能 |
| `DELETE` | `/api/skills/{slug}` | 删除技能（自动备份） |
| `PUT` | `/api/skills/{slug}/md` | 更新 SKILL.md |
| `PUT` | `/api/skills/{slug}/scripts/{name}` | 更新脚本文件 |
| `POST` | `/api/skills/{slug}/scripts` | 创建新脚本 |
| `GET` | `/api/logs` | 列出日志文件 |
| `GET` | `/api/logs/{filename}` | 查看单个日志详情 |
| `GET` | `/api/logs/analyze` | 全局日志聚合分析 |
| `POST` | `/api/optimize/suggestions` | LLM 驱动的智能优化建议 |
| `GET` | `/api/status` | 系统状态 |
| `GET` | `/health` | 健康检查 |

### 启动管理端

```bash
# 一键启动（管理后端 :8686 + 管理前端 :3686）
./start_manage.sh

# 或分别启动：
cd manage_backend && uv run python server.py --port 8686     # 管理后端
cd manage_frontend && npm install && npm run dev               # 管理前端（自动代理到管理后端）
```

---

## 环境变量

### 必填

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `DASHSCOPE_API_KEY` | 阿里 DashScope API 密钥（PPT 生成需要，用于 qwen-image 出图） |

### 可选

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_MODEL` | 模型标识 | `deepseek-v4-pro` |
| `DEEPSEEK_BASE_URL` | API 基础地址 | `https://api.deepseek.com/v1` |
| `PORT` | 后端端口 | `8585`（开发）/ `8046`（Docker） |
| `HOST` | 绑定地址 | `0.0.0.0` |
| `SEARXNG_BASE_URL` | SearXNG 实例地址（需自部署） | `http://localhost:8080/search` |
| `SEARXNG_MAX_ATTEMPTS` | SearXNG 重试次数 | `3` |
| `SEARXNG_REQUEST_TIMEOUT` | SearXNG 请求超时（秒） | `30` |
| `VISION_MODEL` | 视觉模型标识（用于 `vision_analyze` 图片分析/OCR） | `openai/qwen-vl-max` |
| `VISION_API_KEY` | 视觉模型 API 密钥（DeepSeek 无视觉能力，需单独配置） | — |
| `VISION_API_BASE` | 视觉模型 API 地址 | 阿里百炼 OpenAI 兼容端点 |
| `SSE_CACHE_ENABLED` | 是否启用 SSE 缓存 | `true` |
| `SSE_CACHE_MAX_SIZE` | 最大缓存条数 | `500` |
| `SSE_CACHE_TTL` | 缓存 TTL（秒） | `86400`（24h） |
| `WORKERS` | Gunicorn 进程数 | `4` |
| `TIMEOUT` | Gunicorn 超时（秒） | `600` |
| `SANDBOX_ENABLED` | 启用多租户沙箱隔离（未启用则命令走本地 `subprocess`） | `false` |
| `SANDBOX_IMAGE` | 沙箱镜像标识 | `python:3.12` |
| `SANDBOX_POOL_SIZE` | 预热池大小（启动时预建的空闲沙箱数） | `3` |
| `SANDBOX_DOMAIN` | OpenSandbox 服务地址 | `localhost:8080` |
| `SANDBOX_PROTOCOL` | OpenSandbox 协议 | `http` |
| `SANDBOX_API_KEY` | OpenSandbox API 密钥 | `123456` |
| `SANDBOX_TIMEOUT_MINUTES` | 单沙箱硬性存活上限（分钟），活跃自动续期 | `30` |
| `SANDBOX_IDLE_MINUTES` | 租户闲置多久后回收其沙箱（分钟） | `15` |
| `OFFICE_JWT_SECRET` | ONLYOFFICE JWT 密钥（后端与 DocServer 共享；**留空则关闭在线编辑**，前端回退下载） | — |
| `OFFICE_PORT` | DocumentServer 容器对外端口（8080 被 OpenSandbox 占，用 8081） | `8081` |
| `OFFICE_DOCSERVER_URL` | 浏览器访问 DocServer 的地址（加载 api.js） | `http://localhost:8081` |
| `OFFICE_BACKEND_URL` | DocServer 容器回访后端的地址（download/callback），**不能用 localhost** | `http://host.docker.internal:8585` |

---

## 技术栈

### 后端

| 组件 | 技术 |
|------|------|
| 语言 | Python ≥ 3.10 |
| Agent 框架 | Google ADK ≥ 1.0.0 |
| 大模型 | DeepSeek（via LiteLLM） |
| HTTP 框架 | FastAPI + Uvicorn |
| 生产部署 | Gunicorn + UvicornWorker |
| 文件处理 | python-pptx、pandoc、LibreOffice |
| 包管理 | uv（hatchling 构建） |
| 测试 | pytest + pytest-asyncio + httpx |

### 前端

| 组件 | 技术 |
|------|------|
| 框架 | React 19 + TypeScript |
| 构建 | Vite 6 |
| 样式 | Tailwind CSS 4 |
| Markdown | react-markdown + remark-gfm |
| 图标 | lucide-react |
| 动画 | motion (Framer Motion) |

---

## 二次开发

### 1. 新增一个工具（FunctionTool）

在 `backend/app/tools.py` 写一个函数（第一个/末尾参数按需接 `tool_context: ToolContext` 拿到 `user_id`、session state），docstring 会作为工具说明喂给模型：

```python
def my_tool(query: str, tool_context: ToolContext) -> dict:
    """一句话说清这个工具干什么、什么时候用、返回什么。"""
    user_id = str(tool_context.state.get("_sbkey") or tool_context.user_id or "default_user")
    ...
    return {"success": True, ...}
```

然后在 `backend/app/agent.py` 的 `root_agent.tools=[...]` 里注册 `FunctionTool(my_tool)`，并在 `backend/app/instruction.md` 里补一句工具说明（让模型知道何时调用）。

### 2. 给工具加解说卡片

在 `backend/app/narrator_rules.py` 的 `TOOL_LABELS` 中加映射，工具调用才会生成友好卡片：

```python
TOOL_LABELS = {
    "my_tool": {"label": "友好中文名", "icon": "🔧", "detail": "工具做什么的详细说明"},
    "_search": {"label": "搜索信息", "icon": "🔍", "detail": "查找相关资料和信息"},  # _ 前缀=子串模糊匹配
}
```

未匹配的工具名自动转成标题大写（`run_command` → `Run Command`），显示 🔧。

### 3. 新增一个 Skill（技能）

在 `backend/app/skills/<skill-name>/` 下放 `SKILL.md`（分步指导）+ `scripts/`（Python 脚本），然后在 `agent.py` 里 `load_skill_from_dir(...)` 加进 `SkillToolset(skills=[...])`。模型通过 `list_skills`/`load_skill`/`run_skill_script` 自动发现调用。也可以在管理端 `/skills` 页面在线创建/编辑（自动存版本快照）。

### 4. 工作台支持一种新文件类型 / 编辑器

编辑区在 `frontend/src/Workspace.tsx` 里**按后缀路由**：`.excalidraw`→`WhiteboardEditor`，office 类型→`OfficeEditor`，其余→内联预览/下载。要接新编辑器：

1. 写一个组件，用 `GET /files/raw` 读、`PUT /files/raw` 写（都带 `user_id`+`path`）。
2. 在 `Workspace.tsx` 的后缀判断里加一个分支路由到它。

后端文件读写走 `server.py:_safe_user_path`（已带 `../` 越权防护），一般无需改后端。若新类型也要在线协同编辑，参考 `/office/*` 网关的 JWT 模式。

### 5. 换模型 / 供应商

`backend/app/create_model.py` 是模型工厂，统一走 LiteLLM，支持 10+ 供应商。改 `.env` 里的 `MODEL_PROVIDER`/`MODEL_NAME` 即可切换，无需改代码。

---

## 联系作者
![weichat.png](docs/weichat.png)

---

## 致谢

PPT 生成功能参考了 [dashi-ppt-skill](https://github.com/chuspeeism/dashi-ppt-skill) 的风格预设与出图提示词设计，感谢开源贡献。