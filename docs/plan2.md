# AI Office — 界面与流程优化计划（plan2）

> 目标：把「首页 = 扁平启动器」升级为「工作台 = 生成 + 管理 + 预览」，并让 5 个编辑器的
> AI 编辑体验统一、可发现。基线见 `docs/plan.md`（M0–M6 已完成）与 `docs/architecture.md`。
> 设计稿：`docs/home.png`（首页）、`docs/ppt.png`（演示编辑器）。
>
> 原则（ponytail）：先复用已移植的 genoffice 能力和已建好的后端 API，再考虑新增；
> 客户端引擎已能渲染各类文档，缩略图/预览走客户端，后端保持薄。

## 1. 现状 vs 设计稿：差距分析

| 设计稿元素（home.png） | 当前实现 | 差距 / 结论 |
|---|---|---|
| 左栏项目/文件夹树（工作区、收藏、回收站、最近树） | 扁平「最近」列表 | **projectApi 后端已就绪（projects/timeline/conversations），缺 UI** |
| 中间的对话流 + 「研究报告已完成」结果卡 | 只有一个 textarea + 静态快捷卡 | 生成其实发生在编辑器内（AiPanel autoRun）；首页需把「发送→跳编辑器流式」串成连贯观感 |
| 右侧文档实时预览 + Open/Download/Share | 无 | **缺缩略图能力**；实时渲染成本高，改为「保存时客户端出缩略图」 |
| 快捷动作卡（带图标，点了直接生成） | 卡片只**预填**文本，不发送 | 改为一键生成（或预填并聚焦） |
| 顶部搜索 / 通知 / 头像 | 无 | 加一个全局 topbar（搜索文档 + 账户菜单） |

| 设计稿元素（ppt.png） | 当前实现 | 差距 / 结论 |
|---|---|---|
| 完整 ribbon + 缩略图栏 + 画布 | 已移植（slides app 原样保留） | ✅ 基本齐全 |
| 选中图片浮动「Replace image」工具条 | pptx-engine 换图能力已接（M4.4 `insertImageUrl`） | 验证浮动工具条 UX，确保联动 AI 图库 |
| 「AI Assistant / Image」双 tab + 图库网格 | AiPanel 已存在；图搜走 `/ai/image-search` | 统一 AI 面板样式 + 图库 tab；图库**不限 PPT，5 个 app 通用**；位置左右皆可 |
| 操作 toast（Image replacement undone / Undo） | 有 undo 栈，toast 视各 app | 统一「AI 改动可撤销」的反馈样式 |

**总结**：编辑器侧（ppt.png）大体已就绪，重点是**统一与打磨**；首页侧（home.png）是**真正的功能缺口**，也是本计划主战场。

## 2. 设计稿里不合理 / 高成本的点 + 取舍

1. **右侧「文档实时预览」**：对 pptx/docx 做实时渲染要在首页加载整套引擎（重），后端又无 office 库无法服务端出图。
   - 取舍：**保存时由客户端引擎渲染首页/首帧为 PNG**（docx 分页首页 / pptx `buildRenderSlide(0)` / sheets 首屏 / markmap SVG / pdf.js 首页），作为文档缩略图存一份小 blob。首页/最近列表显示**静态缩略图**，而非实时预览。点开才加载引擎。
2. **首页内嵌完整对话流**：生成靠的是编辑器 renderer 里的 Agent（引擎在那儿）。在首页 shell 里再跑一套 Agent 会重复实现且难以承接编辑动作。
   - 取舍：**首页是启动器**。发送后立刻跳到目标编辑器，AiPanel 自动流式（现有 `pendingPrompt`/`?gen=` autoRun 机制）。视觉上让「首页 composer → 编辑器 AI 面板」平滑过渡，而不是在首页假装聊天。
3. **回收站 / 收藏 / 共享给我**：当前是「注册即单人单组织」，无多用户共享、无软删除表。
   - 取舍：先做**收藏（star）**和**软删除（回收站）**（轻量，Document 加两个布尔/时间字段）；「共享给我」等多用户成员体系延后（YAGNI，等真有多用户组织）。
4. **顶部「已升级 / 套餐」**：无计费体系。
   - 取舍：**不做**（占位都不放，避免误导）。

## 3. 重新规划的端到端流程（用户旅程）

```
登录/注册
  → 工作台首页（launcher + 项目树 + 最近/缩略图 + 全局搜索）
      → [新建/快捷卡/一句话] 选择类型 + prompt
          → 跳目标编辑器，AI 面板自动流式生成（可见进度）
              → 编辑（AI 对话改写 / 插改图表 / 换图 / 手动编辑，改动可撤销）
                  → 保存（自动出缩略图 + 版本）
                      → 分享（只读链接）/ 导出 / 移动到项目
  → 返回工作台：最近以缩略图卡呈现，按项目归类，可搜索、收藏、回收站
```

关键改进点：
- **一处入口，多类产物**：首页一个 composer + 类型选择 → 文档/PPT/表格/思维导图/（PDF 打开）。
- **生成即进编辑器**：不割裂「先聊后开」；发送直接进编辑器看着它长出来。
- **管理闭环**：项目树 + 缩略图 + 搜索 + 收藏 + 回收站，让「回来找文件」顺畅。
- **AI 编辑一致**：5 个 app 的右侧 AI 面板同一套外观/交互（品牌、可撤销反馈、图库 tab）。

## 4. 分阶段落地

### P1 — 首页信息架构（复用已建后端，纯前端）
- **P1.1 项目树侧栏**：用现成 `projectApi.getProjects/getTimeline`。侧栏 = 工作区（全部/收藏/回收站）+ 项目列表 + 项目内文档。点项目→过滤最近列表。**新增抽象为零，全是已建 API。**
- **P1.2 最近改为缩略图卡片网格**：DocMeta 已有 title/type，先用「类型图标 + 标题 + 时间」卡片（无缩略图也能上线）；缩略图在 P2 补。
- **P1.3 快捷卡一键生成**：卡片点击直接 `send(prompt)` 而非仅预填（保留「编辑再发」入口）。
- **P1.4 全局 topbar**：文档搜索框（前端过滤 `listDocuments` 结果，量大再加后端 `?q=`）+ 账户菜单（退出/邮箱）。
- 涉及文件：`apps/docs/src/renderer/shell/{Home,Shell}.tsx` + `web-adapter.ts`（已导出 `listDocuments`；补 `getProjects` 透传）+ `styles.css`。

### P2 — 缩略图与预览（客户端渲染，后端存图）
- **P2.1 保存时出缩略图**：各 app 保存后用本地引擎渲染首页/首帧→canvas→PNG(≤~50KB)。
  - docx：分页引擎首页；pptx：`buildRenderSlide(opened,0)`；sheets：首屏截图；markdown/mindmap：markmap SVG→PNG 或前几行；pdf：pdf.js 首页。
- **P2.2 后端存缩略图**：`Document` 加 `thumb_key`（或复用 blob 存 `.../thumb.png`）；`GET /documents/{id}/thumb`。`listDocuments` 返回 thumb URL。
- **P2.3 首页右侧预览面板**：选中最近卡 → 右栏显示缩略图 + 元信息 + Open/Download/Share 三键（Open=openDoc，Download=blob，Share=P3）。**静态缩略图，非实时渲染**（对齐 home.png 但成本可控）。

### P3 — 编辑器 AI 体验统一 + 文档动作
- **P3.1 AI 面板统一**：5 个 app 的 AiPanel 统一外观（品牌 AiOfficeMark、可撤销 toast、空态引导）。面板位置左右皆可（不强制右侧），各 app 沿用自身习惯即可。
- **P3.2 图库 tab 全 app 通用**（不限 PPT）：把 slides 已有的「Image」图库 tab（搜索 `/ai/image-search` + 上传 + AI 建议 + 缩略图网格）抽成共用组件，**docs / slides / sheets / markdown / 思维导图都挂上**——各 app 已有各自的插图能力：
  - docs：TipTap 插图 / `insert_image` 工具；slides：`insertImageUrl` 换图/插图；
  - sheets：单元格图片 / 浮动图片；markdown & 思维导图：`data:` URL 内联插图。
  - 图库选中一张 → 调用当前 app 的插图/换图入口。共用的是「找图 + 选图」UI，落地各 app 自有 API。
- **P3.3 图片替换浮动条**（对齐 ppt.png）：选中图片→浮动「替换图片」→打开图库 tab（搜索/上传/AI 建议）→换图，带 undo toast。slides 链路已通（M4.4），先验证打磨，再推广到支持图片替换的 app。
- **P3.4 分享 UI**：接后端已建 `POST/GET/DELETE /documents/{id}/share`（M5）→ 编辑器/首页「分享」弹窗生成只读链接、可撤销。**后端已就绪，缺前端。**
- **P3.5 版本历史 UI**：接 `GET /documents/{id}/versions` + `restore`（M5 已建）→ 编辑器侧抽屉列版本、可回滚。

### P4 — 文档管理增强（轻量后端字段）
- **P4.1 收藏**：`Document.starred` + `PATCH /documents/{id}`；首页「收藏」筛选。
- **P4.2 回收站（软删除）**：`Document.deleted_at`；`DELETE` 改软删 + `POST /{id}/restore-doc`；列表默认排除、回收站视图展示、可彻底删除。
- **P4.3 移动到项目**：接已建 `POST /projects/move-file`（M3）→ 首页拖拽或右键「移动到项目」。

## 5. 明确不做（YAGNI）

- 计费/套餐/「已升级」入口。
- 多用户组织成员体系、「共享给我」协作（等真有多租户多用户需求）。
- 实时协同编辑（CRDT/Yjs）——先单写锁（已有）。
- 首页实时渲染预览（用保存时缩略图替代）。
- 服务端出缩略图 / 服务端解析文档（后端保持薄，渲染留客户端）。

## 6. 建议实施顺序与理由

1. **P1** 最先：纯前端、全部复用已建 API，一天量级即可让首页「像 home.png 的骨架」。
2. **P3.4 / P3.5**（分享、版本 UI）紧随：后端 M5 已就绪，只差前端，性价比极高。
3. **P2** 缩略图：让首页从「列表」变「卡片墙」，观感提升最大，但需每个 app 加渲染钩子，工作量集中。
4. **P4** 管理增强：加字段 + 迁移（注意无 Alembic，用可 create_all 的新列/新表策略）。
5. **P3.1/P3.2/P3.3** AI 面板统一、图库全 app 通用、换图打磨：体验收尾。

> 里程碑验收：P1 后首页可按项目浏览、一键生成、搜索；P2 后有缩略图卡与右侧预览；
> P3 后分享/版本/换图闭环；P4 后收藏/回收站/移动齐全。每阶段保持 e2e 可跑（serve.py 单源）。
