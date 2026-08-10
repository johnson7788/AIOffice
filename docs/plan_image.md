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

> 落地更正：实际 API 前缀是 **`/gallery`**（不是 `/assets`）——docs SPA 在 base `/` 下把构建产物发到 `/assets/*.js`，`/assets` 会在 nginx 被静态资源遮蔽。A1–A4 已全部完成。

## A5（新增计划）：首页独立「我的图库」入口
**用户需求**：首页左侧「思维导图」下面加一个「我的图库」入口，点开后展示所有已有图片，并支持上传 / 从文献（文档）提取图片。当前图库只藏在各 app 插入图片弹窗的 tab 里，缺一个"直接浏览整个图库"的首页入口。

### 范围：只改一个文件，零后端、零新组件（ponytail 复用）
后端 `/gallery`（list/upload/extract/delete）已就绪，**无需任何后端改动**；共享 `packages/ui/src/ImageGallery.tsx` 已支持上传/提取/删除，**直接复用**。工作全在 `apps/docs/src/renderer/shell/Home.tsx`。

### 改动点 `apps/docs/src/renderer/shell/Home.tsx`
1. **侧栏入口**：在「+ 思维导图」按钮下方加一个「我的图库」按钮（与现有 kind 按钮同风格）。
2. **浏览态**：新增 `showGallery: boolean` state。点按钮 `setShowGallery(true)`；渲染时 `showGallery` 为真则用一个全屏/主区容器包住 `<ImageGallery>` 取代常规首页主区（或叠加 modal，二选一，取更省的）。
3. **浏览模式复用组件**：`ImageGallery` 已有 `gallery={{ docId }}` → 展示"我的图库" tab（列表 + 上传 + 从文档提取 + 删除）。首页无当前文档 → 传 `gallery={{ docId: null }}`（"从文档提取"按钮在 docId 为空时已 disabled，符合预期；用户仍可上传 + 浏览 + 删除）。
   - **onPick**：首页无编辑器可插入 → onPick 设为空操作（或后续做"下载/预览大图"，先留空）。ponytail：浏览态不做插入，需要时再加。
   - **onClose**：`setShowGallery(false)` 回到常规首页。
4. **无新 CSS**：`ImageGallery` 用内联样式；容器复用首页现有 `.home` 布局或一个薄 wrapper。

### 从文献提取的路径说明
「上传文献提取图片」= 用户先把 PDF/office 文件作为文档上传（现有 `/documents`），在图库里对该文档调 `/gallery/extract-from/{docId}`。首页浏览态 docId 为 null，所以"从文档提取"在**首页入口**默认不可用；真正的按文档提取仍在"打开某文档后的插入弹窗"里可用（A3 已实现）。若要在首页也能选文档提取，需再加一个"选择文档"下拉（延后项，见下）。

### 延后项（勿现在做）
- 首页图库的"从文档提取"选择器（下拉选已上传文档 → extract-from）。
- onPick 大图预览 / 下载。
- 图库项缩略图、按内容 hash 去重（沿用总延后项）。

### 验收
- 首页侧栏出现「我的图库」，点开展示 `/gallery` 全部图片，可上传、可删除、可返回。
- docs tsc + build 绿（沿用现有门禁过滤）。
- e2e（可选）：登录→首页→点「我的图库」→上传 1×1 PNG→列表出现→删除。
