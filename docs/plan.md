# AI Office SaaS 实施计划（全面移植 genoffice）

> **决策**：弃用 ONLYOFFICE / OpenSandbox 沙箱 / 旧 office-op 桥。全面采用 genoffice 的引擎 + agent + 编辑器，移植成浏览器访问、可部署到服务器的多租户 SaaS。
> 参考：`/Users/admin/git/genoffice`（桌面 Electron 版）。原型：`home.png`（对话式首页 + 生成物预览）、`ppt.png`（编辑器 + AI 侧栏）。

---

## 1. 核心洞察：移植 = 换掉 Electron 主进程边界

genoffice 的编辑能力全在 **renderer（React，浏览器技术）**：
- docs = Tiptap/ProseMirror，sheets = Univer，slides = 自研 canvas，pdf = pdf.js，markdown。
- AI 编辑靠 `packages/agent-core` 的 ReAct 循环 + 各 app 的 skill/tools（块寻址读写、插图表、web/image search）。

renderer 唯一依赖的外部面 = preload 暴露的两个全局对象：
- `window.desktop`（`DesktopApi`）：文件开/存、AI 流式、搜索、附件、窗口/标签。
- `window.projectApi`（`ProjectApi`）：会话/项目/时间线持久化。

**因此 SaaS 化 = 用浏览器适配器 + FastAPI 后端重新实现这两个对象，renderer 代码基本原样保留。** 引擎跑在**客户端**（浏览器/Web Worker/WASM），后端保持薄。这就是 genoffice 现有设计，只是把「Electron 主进程 ↔ renderer」这条 IPC 边界换成「后端 HTTP/SSE ↔ 浏览器」。

---

## 2. 目标架构

```
┌──────────────── 浏览器 SPA ────────────────┐
│ Web Shell（首页对话 + 编辑器标签, 替代 apps/shell）│
│ ├ docs renderer (Tiptap + docx-engine)        │
│ ├ sheets renderer (Univer + xlsx-wasm)        │  引擎在客户端跑
│ ├ slides renderer (canvas + pptx-engine)      │
│ ├ pdf renderer (pdf.js) / markdown            │
│ └ window.desktop / window.projectApi 浏览器适配器│──HTTP/SSE──┐
└───────────────────────────────────────────────┘            │
                                                    ┌──────────▼──────────┐
                                                    │ FastAPI 后端（薄）    │
                                                    │ auth/租户            │
                                                    │ model transport 代理  │ ← 服务端持模型 key
                                                    │ web/image search 代理 │ ← 移植 ai-search
                                                    │ 文件/版本 元数据       │
                                                    │ 会话/项目 (projectApi) │
                                                    └───┬────────┬─────────┘
                                                     ┌──▼──┐  ┌──▼─────────┐
                                                     │ PG  │  │ 对象存储     │
                                                     └─────┘  │(MinIO/S3)   │
                                                              │ .docx/.pptx │
                                                              │ .xlsx blob  │
                                                              └────────────┘
```

- 文档以**原生文件**（.docx/.pptx/.xlsx blob）存对象存储 —— 沿用 genoffice「原文件是唯一真相，改动是窄 patch」的哲学。
- 打开：浏览器拉 blob → 客户端引擎解析 → 编辑 → 序列化（字节级 patch）→ 上传新版本。后端不碰文档内容，只管鉴权/存取/版本。
- 计算在客户端 → 后端天然可水平扩展、成本低。

---

## 3. 移植边界：`window.desktop` / `window.projectApi` → 后端 API 映射

| IPC 分类 | 现有 IPC（Electron） | Web 适配 → 后端 |
|---|---|---|
| 文件开/存 | openDocx/saveDocx/saveDocxAs/getRecentFiles/pickImage | 浏览器 file picker + `GET/PUT /documents/{id}/blob`、`GET /documents`（recent） |
| 导出/打印 | exportPdf/print/printPdfBuffer/saveMergedPdf | 客户端生成 → 浏览器下载/打印（`window.print`），无需后端 |
| AI 流式 | aiStream/aiStreamCancel/aiChat/onAiStream | `GET /ai/stream`(SSE) + `POST /ai/cancel`，实现 `AgentTransport`（见 §6） |
| AI 账号 | aiGskStatus/aiGskLogin（Genspark） | **删除**，换成本项目 auth；模型 key 只在服务端 |
| 搜索/取图 | webSearch/imageSearch/fetchImage | `GET /ai/web-search`、`/ai/image-search`、`/ai/fetch-image`（移植 ai-search，服务端跑，绕 CORS） |
| 附件 | pickAttachments/addAttachmentPaths/readAttachment/readAttachmentImage/addPastedImage | 浏览器上传 → `POST /files`；`file-parse` 服务端抽取文本 |
| 窗口/标签 | openNewTab/listDocsTabs/focusDocsTab | SPA 路由（react-router），前端内部实现 |
| 关闭/保存生命周期 | onCloseCheck/reportCloseSaveResult 等 | `beforeunload` + 自动保存，前端实现 |
| i18n | getLanguage/onLanguageChanged | 前端本地实现（复用 `packages/i18n`） |
| 会话/项目 | projectApi.*（resolveChat/appendChat/loadChat/list/create/timeline…） | `/conversations`、`/projects`、`/timeline` → PG（见 §7 数据模型） |

> 实施要点：把 Electron 的 `src/preload` + `src/main` 整层替换为一个 `web-adapter` 模块，导出同名 `DesktopApi`/`ProjectApi` 实现，`contextBridge` 换成直接挂 `window`。renderer import 不改。

---

## 4. 前端工程改造

- 保留：`apps/*/src/renderer`、`packages/{docx-engine,pptx-engine,pptx-render,file-parse,agent-core,ai-provider,ai-search,i18n,ui,project-store,markdown}`。
- 删除/替换：`apps/*/src/main`、`apps/*/src/preload`、`apps/shell`（Electron 壳）、`electron.vite.config`、`dist:mac/win`、自动更新、`electron-transport.ts`。
- 新增：
  - `web-adapter`：实现 `DesktopApi`/`ProjectApi`（§3）、`HttpAgentTransport`（§6）。
  - **Web Shell**（替代 apps/shell）：首页（对话生成）+ 编辑器路由 + 登录态。对齐原型（§8）。
  - 各 app renderer 打包成可路由挂载的模块（Vite 多入口或微前端 iframe，首期用 iframe 隔离各编辑器最省事）。
- 构建：Vite 纯前端产物（静态资源），nginx 托管；去掉一切 Electron 依赖。

> ponytail：首期各编辑器用 iframe 承载（`/editor/docs?doc=...`），复用现成 renderer 几乎零改；等要跨编辑器共享状态再考虑单包多路由。

---

## 5. sheets 的 Rust xlsx sidecar（唯一硬骨头 / spike）

现状：sheets 的 .xlsx 导入导出走 Rust sidecar（calamine + IronCalc），Electron 里当子进程调。Web 无子进程。两条路：
- **A（首选，客户端一致性）**：Rust → **WASM**（wasm-bindgen），浏览器 Web Worker 里跑。calamine/IronCalc 是纯 Rust，可行；需评估体积/性能。
- **B（兜底）**：后端跑成 `POST /sheets/parse`、`/sheets/serialize` 微服务，浏览器上传 blob 换 JSON。破坏「计算在客户端」，但改动小。

**M1 前先做 spike 定 A/B**。docs/slides/pdf 无此问题（纯 TS/JS）。

---

## 6. AI Agent（复用 agent-core，换 transport）

- 复用 `packages/agent-core`（ReAct loop、上下文压缩、快照回滚）+ 各 app skill/tools（docs 已看：块寻址读写、插/改图表、web/image search；slides 有 `generate_deck` 生成整套 PPT）。
- 写 `HttpAgentTransport implements AgentTransport`：`stream()` → 打 `GET /ai/stream`(SSE)，把 delta/tool_call/stop_reason 事件回吐给 loop；`cancel()` → `POST /ai/cancel`。
- 后端 `/ai/stream`：注入服务端模型 key（移植 `packages/ai-provider` 到 Python，或后端直接用 litellm 代理 Anthropic/OpenAI），按租户 plan 选模型 + 限流 + 用量计数。
- 工具执行仍在**客户端**（tools 操作 Tiptap/Univer/canvas 实例）；只有 web_search/image_search/fetch_image 走后端代理。
- **对话生成（home.png）**：开一个空白编辑器 + 用对应 skill 跑 agent（如 slides 的 generate_deck），生成物即编辑器内容 → 保存成文档。长生成在客户端跑，SSE 只传模型流。

---

## 7. 多租户 / 数据模型 / 持久化

- 租户：`Organization` 1—N `User`；所有资源带 `org_id`，接口强制过滤。
- 认证：邮箱密码 + JWT（access/refresh），预留 OAuth。替换 genoffice 的 Genspark 账号。
- 表：
  - `organizations(id,name,plan)` / `users(id,org_id,email,pwd_hash,role)`
  - `documents(id,org_id,owner_id,title,type,blob_key,created,updated)` + `document_versions(id,doc_id,blob_key,created)`
  - `document_acl(doc_id,user_id,perm)` / shares(token,doc_id,perm,expires)
  - `projects` / `conversations` / `messages`（承接 projectApi：resolveChat/appendChat/loadChat/timeline）
  - `assets(id,org_id,blob_key,kind)`（附件/图片）
  - `usage(org_id,day,tokens,generations)`（配额计数）
- 对象存储：MinIO（S3 兼容）存 blob；PG 存元数据。

---

## 8. 前端 UX（对照原型）

**首页 `home.png`**：左侧栏 工作台/文件/最近（projectApi）；中间对话框 "What would you like to create?" + 快捷卡片 + 消息流（工具进度、"研究报告已完成"卡）；右侧生成物预览 + `Open editor`/`Download`/`Share`。→ 建会话跑 agent 生成 → 建 document → 跳编辑器。

**编辑器 `ppt.png`**：slides renderer（浏览器）+ 右侧 AI 侧栏：选中图片→Replace image（图库搜索/上传/AI 建议 = image_search + fetch_image + assets）；"Ask AI about…"→按选区改写（agent tools）。这些**都是 genoffice 已有工具**，Web 化即得，不用再造 op 桥。

**新增页**：登录/注册、分享只读页（share token 免登录看/下载）。

---

## 9. 协同编辑

genoffice 无内建实时协同（桌面单文件）。弃用 ONLYOFFICE 后此能力需自己补：
- **首期：单写锁**（一个文档同时一个编辑者，其余只读 + 抢锁），最省事，满足多数场景。
- **后续：CRDT**（Tiptap 接 Yjs、Univer 有协同方案）真需要多人同编再上。
- ponytail：先单写锁，别一上来搞 CRDT。

---

## 10. 部署

docker compose：`nginx`(TLS+静态SPA+/api反代) / `app`(FastAPI×N) / `postgres` / `minio`。
- 无 DocumentServer、无沙箱容器 —— 比原方案简单很多。
- Alembic migrations；MinIO bucket 初始化脚本。
- 演进 k8s：app 无状态 Deployment + HPA；PG/MinIO 云托管。

---

## 11. 安全

- 多租户隔离：查询强制 org_id；文档 ACL；分享短时 token 只读。
- 模型 key / 搜索 key 只在服务端，前端永不下发（genoffice 原本前端不存 key，保持）。
- `sanitizeAgentPayload`（agent-core 已有）：出站前脱敏 API key/凭据 —— 保留。
- 上传：类型/大小限制、防路径穿越、blob 走对象存储不落可执行目录。
- 越权测试：跨租户取文档/blob/会话/分享。

---

## 12. 里程碑

- **M0 骨架 + spike**：compose 起 PG/MinIO/FastAPI；**sheets WASM/服务 spike 定案**；单个 app（docs）renderer 剥离 Electron、浏览器跑通空文档。
- **M1 账号 + 存储**：JWT+租户；`window.desktop` 文件面（开/存/recent）接对象存储；docs 打开/编辑/保存 .docx 全链路。
- **M2 AI 编辑**：`HttpAgentTransport` + `/ai/stream` + 搜索代理；docs agent 块级改写/插图表跑通（对齐 ppt 侧栏交互思路）。
- **M3 对话生成 + Shell**：首页对话 → agent 生成 → 建文档 → 预览/打开（对齐 `home.png`）。
- **M4 slides + sheets**：slides renderer（generate_deck + 换图，对齐 `ppt.png`）；sheets 按 spike 结论接入。
- **M5 协同 + 分享 + 生产化**：单写锁、分享只读页、版本、配额、限流、越权测试。
- **M6 pdf/markdown + 部署文档**：补齐剩余 app、一键部署、运维手册、k8s 骨架。

每里程碑留一条端到端可运行验证。

---

## 13. 风险 / spikes

- **sheets Rust sidecar 上 Web**：最大不确定性 → M0 先 spike（WASM 体积/性能 vs 后端服务）。
- **各 renderer 与 Electron 的隐藏耦合**：除 `window.desktop/projectApi` 外可能散落 `window.electron`/Node API → 移植第一个 app（docs）时全量 grep 清点。
- **AgentTransport 语义对齐**：SSE 需精确复刻 electron-transport 的 delta/toolCall/stopReason/onDone/onError 事件序，否则 loop 的取消/压缩/回滚逻辑出错。
- **协同缺失**：弃 ONLYOFFICE 即丢内建协同 → 首期单写锁兜底，别欠账无声。
- **打包体积**：客户端塞引擎+WASM，首屏大 → 按 app 懒加载/分包。
- **License**：genoffice Apache-2.0（OK）；`ee/` 保留、GenOffice/Genspark 商标不可用 → 换自有品牌。

---

## 14. 目标仓库布局（monorepo，直接建在 `newoffice` 空分支）

```
AIOffice/
├─ frontend/                 # 从 genoffice 拷来的 web 化前端（TS）
│  ├─ apps/{docs,sheets,slides,pdf,markdown}/src/renderer   # 原样拷贝
│  ├─ packages/{agent-core,docx-engine,pptx-engine,pptx-render,
│  │            file-parse,i18n,ui,project-store,markdown}   # 原样拷贝
│  ├─ web-adapter/           # 新增：实现 window.desktop / window.projectApi（浏览器版）
│  ├─ shell/                 # 新增：Web Shell（首页对话 + 编辑器路由 + 登录）替代 apps/shell
│  ├─ vite.config.ts         # 新增：纯前端多入口构建（替 electron.vite.config）
│  └─ package.json
├─ backend/                  # 新增：Python FastAPI（薄后端）
│  ├─ app/{auth,documents,ai,files,projects,shares}.py
│  ├─ app/{models.py,db.py,storage.py,settings.py,search.py,provider.py}
│  ├─ alembic/  pyproject.toml (uv)
├─ docker-compose.yml        # nginx + backend + postgres + minio
└─ plan.md
```

> `frontend/` 首期可仍用 npm workspaces（拷 genoffice 的 workspace 结构），只是把 Electron 相关 workspace 剔除。

---

## 15. 拷贝清单（从 `/Users/admin/git/genoffice`）

| 来源 | 处理 | 说明 |
|---|---|---|
| `packages/agent-core` | ✅ 拷贝 | ReAct loop / 压缩 / sanitize。丢 `electron-transport.ts`（renderer 用自己的 transport） |
| `packages/{docx-engine,pptx-engine,pptx-render}` | ✅ 拷贝 | 客户端解析/序列化/patch，浏览器跑 |
| `packages/{file-parse,i18n,ui,project-store,markdown}` | ✅ 拷贝 | file-parse 先客户端跑（附件文本抽取）；project-store 的接口对接后端 projectApi |
| `packages/ai-provider` | ❌ 不拷 → **Python 重写** | 原主进程模型流式；改为后端 `/ai/stream`（litellm） |
| `packages/ai-search` | ❌ 不拷 → **Python 重写** | 原主进程 web/image search + Genspark auth；改为后端搜索代理，换自有搜索源 |
| `packages/electron-utils` | ❌ 丢弃 | Electron 主进程助手 |
| `apps/*/src/renderer` | ✅ 拷贝 | 编辑器 UI 本体，几乎不动 |
| `apps/*/src/{main,preload}` | ❌ 丢弃 → 由 `web-adapter` 替代 | IPC 边界换 HTTP/SSE |
| `apps/shell` | ❌ 丢弃 → 新 `shell/` | Web Shell 重写 |
| `apps/sheets` Rust sidecar | ⚠️ spike | WASM 或 后端服务（§5） |
| 字体 `apps/docs/src/renderer/fonts` | ✅ 拷贝 | 布局度量依赖 |

**salvage 旧 AIOffice 后端（git 历史，非工作树）**：`create_model.py`(litellm 封装)、`/chat/stream` 的 SSE 写法、`/upload` 防路径穿越校验 —— 可复用到新 Python 后端，不从零写。

---

## 16. Python 后端设计（FastAPI，薄）

**职责**：auth/租户、模型 transport 代理、搜索代理、blob/版本存储、projectApi 持久化、配额。**不碰文档内容**（引擎在客户端）。

**技术**：Python 3.12 + FastAPI + uv；SQLAlchemy + Alembic + PostgreSQL；对象存储用 boto3→MinIO/S3；模型走 litellm；JWT 用 pyjwt + passlib。

**端点分组**（对应 §3 映射）：
- `auth`：`/auth/register|login|refresh|logout`
- `documents`：`GET /documents`（列表/recent）、`POST /documents`（建）、`GET|PUT /documents/{id}/blob`（下载/保存新版本，走对象存储）、`/documents/{id}/versions`、`/documents/{id}/share`
- `files`：`POST /files`（附件上传→对象存储）、`GET /files/{id}`；（可选）`POST /files/{id}/extract`（file-parse 若改服务端）
- `ai`（核心）：
  - `GET /ai/stream`（**SSE**）：入参 messages/system/tools（agent-core 请求体）；后端 litellm 流式，逐事件 SSE 下发 → 前端 `HttpAgentTransport` 转成 `AgentTransport` 回调。
  - `POST /ai/cancel`（按 request_id 中断）
  - `GET /ai/web-search`、`GET /ai/image-search`、`GET /ai/fetch-image`（搜索/取图代理，服务端出网绕 CORS，key 只在服务端）
- `projects`：承接 `ProjectApi` 全部方法（resolveChat/appendChat/loadChat/rebindChat/list/create/rename/delete/moveFile/timeline）→ PG

**SSE 契约（关键，需与 agent-core transport 语义对齐）**：每行 `data: {type, ...}`：
- `{type:"delta", text}` → `onDelta`
- `{type:"tool_call", id, name, input, truncated?, inputError?}` → `onToolCall`
- `{type:"stop_reason", reason}` → `onStopReason`（`max_tokens` 触发 loop 截断处理）
- `{type:"done"}` / `{type:"error", message}` → `onDone`/`onError`
> 工具**执行仍在客户端**（操作编辑器实例）；后端只转发模型的 tool_call 意图和文本，不执行工具。web_search 等例外工具的执行 = 客户端调 `/ai/web-search`。

**前端接线点**：`web-adapter` 里 `window.desktop.aiStream` 实现为打开 `/ai/stream` 的 EventSource/fetch-stream，喂给现有 `apps/*/src/renderer/ai/transport.ts`（该文件基本不用改，只是底层从 IPC 换成 SSE）。

---

*已弃用：ONLYOFFICE、OpenSandbox 沙箱、旧 office-op 轮询桥、dashi-ppt 等外部技能（改用 genoffice 原生 generate_deck 等）。后端 TS 主进程逻辑（ai-provider/ai-search）改为 Python。*
