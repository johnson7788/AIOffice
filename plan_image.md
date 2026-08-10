# plan_image.md — 私人图库（Plan A）

## 目标
图库默认展示**用户私人图片**，不再默认联网搜索。用户可以：
1. 手动上传图片到图库；
2. 从已上传的 Office 文件里提取图片进图库；
3. **通过对话（AI Agent）控制**上述操作（列出/提取/删除/搜索图库）。

## 方案取舍：为什么 A 不是 B
- **A（选中）**：给**现有的客户端 Agent** 增加几个 asset 工具 + 一个 `/assets/*` 瘦后端。Agent 仍在浏览器 renderer 里跑（`@genoffice/agent-core` ReAct 循环），工具只是 HTTP 调用 `/assets/*`。契合当前架构（客户端引擎 + 瘦后端），零沙箱。
- **B（放弃）**：像 ADK / openclaw / claude code 那样在**服务端**跑一个能操作文件系统/沙箱的 Agent（参考 `hansen_report/backend/server.py`）。这与本项目"重建时**刻意砍掉沙箱与服务端 Agent**"的架构决策冲突，且需要多租户持久化 session/artifact 服务。放弃。

## 后端（create_all-safe，无 Alembic）
新增独立表 + 派生存储 key，不动现有表结构。

### 数据模型 `backend/app/models.py`
```
Asset(
  id: str PK,
  org_id: str,          # 租户隔离
  name: str,
  mime: str,            # image/png|jpeg|...
  size: int,
  source: str,          # 'upload' | 'doc:<docId>'
  created: datetime,
)
```
Blob key（复用 `storage.py`）：`org/{org}/asset/{id}`。

### 路由 `backend/app/routers/assets.py`（org-scoped，跨租户→404）
镜像 `documents.py` 现有模式（`_check_quota`、`MAX_BLOB_MB`→413、Bearer 依赖）：
- `GET  /assets?q=` — 列表，按 name 过滤（q 可选）。
- `POST /assets?name=` — body=图片字节，校验 `mime.startswith('image/')`，否则 400。source='upload'。
- `GET  /assets/{id}/blob` — 鉴权后 stream 图片（Content-Type=mime）。**注意：走鉴权端点，不用无鉴权的 `/ai/fetch-image` 代理。**
- `DELETE /assets/{id}` — 删记录 + blob。
- `POST /assets/extract-from/{docId}` — 服务端从该文档提取图片，逐张建 Asset（source=`doc:<docId>`），返回新建列表。

在 `backend/app/main.py` include 该 router。

### 提取实现（全部后端，`extract-from` 一个端点吃所有类型）
统一在后端做，Agent 工具 `extract_images(fileId)` 不按类型分叉，任意会话对任意文件都能提取（不依赖某个 app 是否打开）。
- **Office（docx/pptx/xlsx）= 纯 stdlib `zipfile`**：OOXML 就是 zip，图片是 `word/media/*` / `ppt/media/*` / `xl/media/*` 下的原始 png/jpg。读出字节→建 Asset。无需 office 库。
- **PDF = `pypdf`（纯 Python，无二进制依赖）**：遍历页面 XObject 抽图（`page.images`）。够轻、够用，不破坏"瘦后端"。若日后遇到复杂滤镜/CMYK 抽不全，再评估 `pymupdf`（提取质量最好但二进制重依赖）。
- 依赖：`backend/pyproject.toml` 加 `pypdf`（唯一新增；office 走 stdlib）。

### 配额
`extract-from` 与 `POST /assets` 都过 `_check_quota`（复用 documents 的按 org 计数/字节数逻辑）。

## 前端

### 共享组件 `frontend/packages/ui/src/ImageGallery.tsx`（扩展，5 个 app 共用）
- 新增来源切换：**我的图库（默认）** / 联网搜索（fallback，保留现状）。
- 我的图库视图：调 `GET /assets` 渲染；顶部 **上传** 按钮（file picker→`POST /assets`）+ **从文档提取** 按钮（选当前/已上传文件→`POST /assets/extract-from/{docId}`）。
- 插入图片：`GET /assets/{id}/blob`（**鉴权 fetch**）→ dataURL → 交给各 app 现有插入逻辑（复用 P3.2 的 per-app onInsert）。

### 对话控制（客户端 Agent 工具，不加服务端 Agent）
在各 app 现有客户端 Agent 上注册瘦工具（实现即对 `/assets/*` 的 HTTP 调用）：
- `list_assets(q?)` → `GET /assets`
- `extract_images(fileId)` → `POST /assets/extract-from/{fileId}`
- `delete_asset(id)` → `DELETE /assets/{id}`
- `search_assets(q)` → `GET /assets?q=`

Agent 仍 100% 客户端；后端只做存储/提取/鉴权，无沙箱、无服务端 Agent。

## 延后项（在此登记，勿现在做）
- 独立缩略图：先直接返回原图，需要再加。
- 去重：blob sha256 唯一约束，需要再加。

## 验收 / 落地检查
- 后端：`tests/test_assets.py`（roundtrip 上传→列表→blob→删除；跨租户 404；非图片 400；extract-from 一个真实 docx/pptx 断言媒体张数 + 一个带图 pdf 断言张数）。跟随现有 backend pytest 门禁。
- 前端：`ImageGallery` 来源切换 + 上传/提取按钮；tsc + build 绿；至少一个 app e2e 打开图库看到"我的图库"。

## 分阶段
- **A1**：后端 Asset 表 + `/assets` CRUD + upload（无 extract）。
- **A2**：`extract-from`（zipfile 提取 office + pypdf 提取 pdf）。
- **A3**：ImageGallery 我的图库 UI（上传 + 从文档提取 + 插入）。
- **A4**：客户端 Agent asset 工具（对话控制）。
