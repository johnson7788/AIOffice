# AI Office — 当前实现逻辑（架构分析）

> 对应分支 `newoffice`。全面移植自 genoffice（桌面 Electron 版），弃用 ONLYOFFICE / OpenSandbox 沙箱 / 旧 office-op 桥。实施计划见 `plan.md`。

## 1. 核心思想：引擎跑在客户端，后端保持薄

genoffice 的编辑能力全部在 **renderer（React + 浏览器技术）**：

| App | 编辑器引擎 |
|---|---|
| docs | Tiptap / ProseMirror + docx-engine（TS 解析/序列化/patch） |
| slides | 自研 canvas + pptx-engine / pptx-render |
| sheets | Univer + 前端 JSZip（写规划） + 后端 Rust sidecar（读/recalc） |
| pdf | pdf.js + pdf-lib（纯浏览器） |
| markdown | TipTap 编辑纯文本 .md |

renderer 唯一的外部依赖面 = preload 暴露的全局对象（`window.desktop` / `window.projectApi` / `window.slidesApi` 等）。**SaaS 化 = 用浏览器适配器 + FastAPI 后端重新实现这些对象，renderer 代码基本原样保留**：

- 打开：浏览器拉 blob → 客户端引擎解析 → 编辑 → 序列化（字节级 patch）→ 上传新版本。
- 后端不碰文档内容，只管鉴权/存取/版本/代理。
- 计算在客户端 → 后端天然可水平扩展、成本低。

```
浏览器 SPA ──(HTTP/SSE)──▶ FastAPI 后端（薄） ──▶ Postgres（元数据）
  │ 引擎在浏览器跑                    │               + MinIO/S3（blob）
  └ web-adapter（window.* 适配器）     ├── litellm 模型代理（key 只在服务端）
                                     ├── SearXNG 搜索代理
                                     └── Rust xlsx-sidecar（/sheets）
```

## 2. 仓库布局

```
AIOffice/
├─ frontend/            # npm workspaces：apps/* + packages/*
│  ├─ apps/{docs,slides,pdf,markdown,sheets}/src/renderer   # genoffice renderer 原样拷贝
│  ├─ packages/{docx-engine,pptx-engine,pptx-render,agent-core,
│  │            ai-provider,ai-search,file-parse,i18n,ui,project-store}
│  └─ nginx.conf / Dockerfile / vite.*.config.ts
├─ backend/             # Python FastAPI（uv）
│  ├─ app/{main,db,models,settings,security,storage,search,llm,config,ratelimit,locks}.py
│  ├─ app/routers/{auth,documents,projects,sharing,sheets}.py
│  ├─ app/seed/         # 注册时自动种入的示例文档
│  ├─ xlsx-engine/      # vendored Rust sidecar（calamine + ironcalc）
│  └─ tests/
├─ e2e/                 # Playwright 端到端测试（独立，非 workspace）
├─ k8s/aioffice.yaml    # k8s 骨架
├─ docker-compose.yml   # postgres + minio + backend + frontend(nginx)
├─ start.sh             # 本地开发：后端 + 5 个 vite dev
├─ deploy.sh            # 生产：docker compose up --build
└─ plan.md
```

## 3. 前端：web-adapter 移植模式

每个 app 的 `apps/<app>/src/renderer/web-adapter.ts` 实现同名全局对象（import 顺序在 main.tsx 首位），把 Electron 主进程逻辑机械翻译为 HTTP/SSE：

- **文件开/存**：`openDocxPath(id)`→`GET /documents/{id}/blob`（ArrayBuffer + sha256）；`saveDocx`→`PUT /documents/{id}/blob`；`saveDocxNew`→`POST /documents`。ppt/xlsx 同 blob 存储。
- **AI 流式**：`aiStream` = POST `/ai/stream` 的 fetch-stream，解析 `data:` SSE 帧回吐给 renderer 的 `AgentTransport`（transport 层几乎不改，只是底层从 IPC 换成 SSE）。`aiStreamCancel`→`POST /ai/cancel`。
- **搜索/取图**：`webSearch`/`imageSearch`/`fetchImage`→`GET /ai/{web-search,image-search,fetch-image}`（服务端出网绕 CORS）。
- **projectApi**：`resolveChat`/`appendChat`/`loadChat`/`rebindChat`/projects 列表与 timeline → `/projects/*`。
- **登录态**：token 存 localStorage（key `aioffice_token`），`authFetch` 自动带 `Authorization: Bearer`，401 时清 token + reload 回登录。pdf/markdown/sheets/slides 无登录页，复用 docs 的 token（同源）。
- **跨 app 跳转**：`?open=<docId>` / `?gen=<prompt>` / `?tok=<jwt>` URL 参数 + sessionStorage（`aioffice.pendingOpen` / `aioffice.pendingPrompt`）。
- **Node 兼容 shim**：slides/sheets 用 vite `resolve.alias` 把 `node:crypto`/`node:zlib`/`node:fs` 等映射到 `src/renderer/shims/*`（如 zlib→pako.deflate），`Buffer` 由 `buffer` 包 polyfill。

### 各 app 开发端口

| App | 端口 | base（生产） |
|---|---|---|
| docs（主入口，含登录/首页 Shell） | 3585 | `/` |
| slides | 3586 | `/slides/` |
| pdf | 3587 | `/pdf/` |
| markdown | 3588 | `/markdown/` |
| sheets | 3589 | `/sheets/` |

vite dev 代理 `/ai /auth /documents /projects /files /sheets /share` → 后端 `:8585`。注意 `/ai` 代理带 `bypass`：带文件扩展名（`.tsx/.ts/.css`）的请求由 vite 直接服务，避免源码模块被吞。

## 4. 后端：模块与 API

薄后端职责：auth/租户、模型代理、搜索代理、blob/版本存储、projectApi 持久化、配额/限流/单写锁。**不解析文档内容**。

| 模块 | 职责 |
|---|---|
| `db.py` | async SQLAlchemy 2.0，lifespan 启动时 `create_all`（Alembic 延后） |
| `models.py` | Organization/User/Document/DocumentVersion/Project/Conversation/Message/DocumentLock/Share，均带 org_id |
| `security.py` | stdlib **scrypt** 口令哈希 + PyJWT HS256（24h），`get_current_user` HTTPBearer |
| `storage.py` | 本地 FS（默认）或 S3/MinIO（`S3_ENDPOINT` 设置时）；`content_disposition()` 按 RFC 6266 处理中文文件名 |
| `search.py` | httpx → 自建 SearXNG（`SEARXNG_URL`），reshape 为 docs 契约；空 URL→`unavailable` |
| `llm.py` | `stream_turn`：litellm 流式，逐事件产出 IpcStreamChunk（见 §5） |
| `config.py` | `MODEL_PROVIDER`/`MODEL_NAME` → litellm model + kwargs（10 家 provider 映射） |
| `ratelimit.py` | 固定窗口限流中间件（按 JWT sub / IP，/healthz 豁免） |
| `locks.py` | 单写锁（`DocumentLock`，TTL 120s，软 409） |
| `seed.py` | 注册时按 manifest 种入示例文档 |

### API 一览

**auth**（`/auth`）：`POST /register`（自动建 Organization + 种子文档）、`POST /login`、`GET /me`。

**documents**（`/documents`，org 隔离，跨租户→404）：
- `GET ""`（recent 列表）、`POST ""?title=`（body=blob，建 doc+v1）、
- `GET/PUT /{doc_id}/blob`、`GET /{doc_id}/versions`、`POST /{doc_id}/versions/{ver_id}/restore`。
- 配额：`MAX_DOCS_PER_ORG` / `MAX_STORAGE_MB_PER_ORG`（超出→402）；`MAX_BLOB_MB`（超→413）。

**projects**（`/projects`，承接 projectApi 持久化）：
- `POST /resolve-chat{filePath?,tempChatId?}`→`{projectId,chatId}`（按 chat_key 找或建会话）
- `POST /append-chat{projectId,chatId,role,text,tools?,attachments?}`（顺序 seq，会话随文档走）
- `GET /chat?chatId=&limit=`、`POST /rebind-chat`（temp→doc id）
- `GET/POST ""`、`PATCH/DELETE /{pid}`（默认项目不可改名/删除）、`POST /move-file`、`GET /{pid}/timeline`。

**locks**（`/documents`）：`POST /{doc_id}/lock`（acquire/renew/steal→LockOut）、`DELETE /{doc_id}/lock`。

**sharing**（只读分享）：
- owner（`/documents`，需登录）：`POST /{doc_id}/share`、`GET /{doc_id}/shares`、`DELETE /{doc_id}/share/{token}`。
- public（`/share`，免登录）：`GET /{token}`、`GET /{token}/blob`。

**sheets**（`/sheets`，xlsx 读/recalc 代理 → Rust sidecar）：
`POST /open /read-range /read-formulas /read-media /recalc /manifest /read-entries /scan-entries /save /close`。浏览器传 base64，后端维护会话，浏览器永远看不到 fs 路径。

**ai**：
- `POST /ai/stream`（SSE）、`POST /ai/cancel`（按 requestId 取消）、`GET /ai/fetch-image?url=`、`GET /ai/web-search?q=&max=`、`GET /ai/image-search?q=&max=`。

**healthz**：`GET /healthz`→`{"ok":true}`（限流豁免，供探针）。

## 5. AI 流式契约（SSE）

前端 `POST /ai/stream`，body：`{requestId, system, messages: AgentMessage[], tools: AgentToolDef[]}`。后端只转发模型文本 + 解析出的 tool_call 意图，**工具执行在浏览器**。

每帧 `data: {requestId, type, ...}`，type 取值：
- `delta` `{text}` → onDelta
- `tool-call` `{id,name,input,truncated?,inputError?}` → onToolCall（参数流式期间发 `ping` 维持前端静默 watchdog）
- `done` `{stopReason}` / `error` `{message}` → onDone/onError
- `finish_reason=='length'` → `stopReason:'max_tokens'`

消息形状：`user{text,images?}`、`assistant{text,toolCalls?}`、`tool{results:[{id,name,output}]}`；工具定义 `AgentToolDef{name,description,inputSchema}`。

## 6. sheets 的 Rust sidecar（A/B spike 结论 = B 后端服务）

- genoffice 的 sheets xlsx 读写引擎是 Rust 二进制（calamine 0.36 + ironcalc 0.7），协议为 **stdin/stdout NDJSON**（`{version,requestId,command}` ↔ `{version,requestId,ok,result?,error?}`），状态为进程内会话，按 fs 路径寻址文件。
- 结论：**跑在后端**（每个会话一个子进程），而不是编 WASM。理由：fs 路径 + 进程内会话模型与后端 1:1 映射，WASM 需虚拟 FS + Worker 会话状态 + 多 MB wasm，diff 大。
- 实现：`backend/app/xlsx_sidecar.py` 管理子进程（`XLSX_SIDECAR_BIN` 指定二进制，Docker 镜像内已烘焙）；`backend/app/routers/sheets.py` 用 base64 在浏览器和后端间传文件。
- 前端只做**写规划**（`planCellEditsToXlsx`，纯 TS，JSZip+Buffer），读/recalc 走后端 `/sheets/*`。
- 本地：sidecar 需先 `cd backend/xlsx-engine && cargo build --release`（或设 `XLSX_SIDECAR_BIN`），否则 `/sheets/*` 端点不可用。

## 7. 安全

- **多租户隔离**：所有查询强制 `org_id`；跨租户访问统一 404（文档/blob/会话/分享均有越权测试）。
- **凭据**：口令 scrypt 哈希；JWT HS256 24h；模型 key / 搜索 key 只在服务端。
- **配额/限流**：文档数与存储量配额（402）、`MAX_BLOB_MB`（413）、固定窗口限流（429+Retry-After）。
- **单写锁**：PG 表 `DocumentLock`，TTL 过期可被抢占；软 409（只拦其他活跃持锁者）。
- **分享**：短 token 只读，无公开写。
- 注意：FastAPI HTTPBearer 缺 token → **401**（不是 403）。

## 8. 测试

- **backend**（`backend/tests/`，pytest）：auth / documents（roundtrip、跨租户 404、大小限制）/ projects / sharing+locks / sheets api / sheets spike / llm / api（搜索 reshape）。`pytest -q`：36 passed / 2 skipped（skipped = 需 `AIOFFICE_E2E=1` 的 live 模型 e2e）。sheets 测试需先构建 sidecar 二进制。
- **frontend**（各 app `tests/`，vitest）：web-adapter、pdf-edit、doc-text、blank-workbook、pptx-pipeline 等。
- **e2e**（`e2e/`，Playwright，独立）：15 用例，全部确定性、**不调模型**。api.spec 覆盖 healthz/auth/文档 roundtrip/跨租户/静态 SPA 路由；docs-ui.spec 走注册→Home→登录持久→退出→新建文档。测试栈用 `e2e/serve.py`（stdlib 反代镜像 nginx 路由）。

## 9. 已知取舍 / 债务

- 限流为进程内 dict（每副本独立，多副本实际限额 ~N×MAX）；扩展时换 Redis INCR+EXPIRE。
- 无 Alembic（启动 `create_all`），假定全新库；schema 变更需手动/后续补迁移。
- pdf/markdown 导出基于浏览器下载/`window.print`，无原生对话框；markdown 图片内联为 `data:` URL。
- 未做同组织多用户共享/成员管理（YAGNI，单用户注册即单组织）。
- docs 遗留部分已删源码的 Electron 测试文件（cleanup 项）。
