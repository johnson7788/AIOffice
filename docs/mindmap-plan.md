# 思维导图功能 — 开发计划与选型 (branch `mind`)

> 目标：给 AIOffice 增加"思维导图"能力。核心不是"再造一个思维导图软件"，而是
> 把它做成 AIOffice 现有形态的一员：**浏览器内 React 渲染 + web-adapter 走 HTTP/SSE +
> blob/版本存储 + AI 通过工具读写文档 + 多租户隔离**。选型必须服从这个架构，而不是反过来。

---

## 1. 选型硬约束（决策过滤器）

AIOffice 已把 genoffice 5 个应用全部 web 化：docs(3585)/slides(3586)/pdf(3587)/
markdown(3588)/sheets(3589)。每个应用 = `apps/*` npm workspace，renderer 基本原样搬，
`web-adapter.ts` 把 Electron preload 全局重实现为浏览器 HTTP/SSE 适配器。任何思维导图
方案要能落地，必须同时满足：

| # | 约束 | 说明 |
|---|------|------|
| C1 | **能在浏览器里跑（React/JS）** | renderer 是 vite + React 19 的 SPA。Java/C++/Qt/GTK 桌面程序无法进浏览器。 |
| C2 | **有干净可序列化的文档格式** | 要能存成一个 blob（像 .docx/.pptx/.md/.xlsx），走现有 `/documents` 版本存储。 |
| C3 | **AI 能读写这个格式** | AIOffice 的核心卖点是 AI 编辑。格式越接近文本/大纲，AI 工具越好写。 |
| C4 | **后端保持薄（Python）** | 后端只做 auth/租户、模型转发、搜索代理、blob。**不能引入 Java/Spring 渲染服务。** |
| C5 | **License 兼容** | 项目主体 Apache-2.0；优先 MIT/Apache/BSD，避免 AGPL 传染后端。 |
| C6 | **能复用现有 app 骨架** | web-adapter + projectApi + AI-SSE + Home 入口 + nginx 路由 + seed，越复用越省。 |

---

## 2. 候选项逐一评估

### 桌面应用 — 全部淘汰（违反 C1）
| 工具 | 技术栈 | 结论 |
|------|--------|------|
| Freeplane | Java | 桌面程序，进不了浏览器。**唯一价值**：其 `.mm`（FreeMind/Freeplane XML）是导图交换的事实标准，可作为**导入/导出格式**参考。 |
| Vym | C++/Qt | 桌面，淘汰。 |
| Semantik | Python/KDE | 桌面 + KDE 依赖，淘汰。 |
| Labyrinth | Python/GTK | 桌面，淘汰。 |

### 文本/代码驱动 — 与本架构天然契合（满足 C1~C6）
| 工具 | License | 交互 | AI 可驱动性 | 结论 |
|------|---------|------|-------------|------|
| **Markmap** (`markmap-lib`+`markmap-view`) | MIT | 可缩放/折叠/平移的 D3 导图（查看态交互） | ★★★★★ 输入就是 **Markdown 大纲** | **首选**。见下。 |
| **Mermaid.js** (`mindmap` 语法) | MIT | 只渲染（改文本→重渲 SVG） | ★★★★★ 一段文本 | 适合**在文档里内嵌**导图代码块，作为 Markmap 的补充。 |
| PlantUML | GPL + 需 **Java** 渲染服务 | 只渲染 | ★★★★ | **淘汰**：违反 C4（要起 Java 服务）。 |

### Web 应用 — 各有硬伤
| 工具 | 问题 | 结论 |
|------|------|------|
| draw.io | Apache-2.0、可自部署，但是通用绘图，**iframe 嵌入**、`mxGraph` XML 格式复杂难 AI 驱动、体量大 | 不符合"每 app 一个 React renderer + AI 工具"的形态。**仅备选。** |
| Wisemapping | 专业导图 + 协作，但**自带 Java/Spring 后端**（违反 C4），编辑器 mindplot 基于 mxGraph+webpack，塞进 vite/React 成本高，授权条款变更过 | **淘汰。** |
| Excalidraw (`@excalidraw/excalidraw`) | React、MIT、嵌入干净、"好看手绘风" | 但它是**自由白板**，没有层级树/自动布局。AI 驱动=按坐标摆图形（像 slides 自由态），拿不到大纲结构。**≠ 结构化思维导图。** 适合另开一个"白板"产品线，不作为导图主线。 |

### 笔记工具内置 — 淘汰（违反 C1/C6）
Logseq / TiddlyMap 都是整套应用，不是可嵌入组件，无法复用 app 骨架。

---

## 3. 结论与推荐（分阶段）

### 决定性洞察
AIOffice **已经有一个完整 web 化的 markdown 应用**：块级 AI 编辑
（`get_document_context`/`read_blocks`/`insert_content`/`replace_blocks`，见
`apps/markdown/src/renderer/ai/tools.ts`）、`.md` blob 存储、projectApi、AI-SSE 全都在。
一张思维导图**本质就是一份 Markdown 大纲**。用 **Markmap** 把大纲渲染成可交互的树，
就等于：**文档模型、存储、AI 编辑全部复用，只加一个渲染视图。** 这是最省、也最贴合
"AI 可编辑"卖点的路径。

### 推荐路线

**Phase 1（MVP，强烈推荐）= Markmap + Mermaid**
- 思维导图 = Markdown 大纲的**可视化视图**。存的还是 `.md` blob。
- 在 markdown app 里加一个 **"大纲 ⇄ 导图" 视图切换/分屏**（`markmap-view` 渲染当前文档）。
- AI 用**现有的 markdown 工具**改大纲 → Markmap 自动重渲染。**零新增 AI 工具。**
- 顺带支持在 docs/markdown 里内嵌 `mermaid` 的 `mindmap` 代码块（渲染成 SVG），满足"写文档随手画导图"。
- 交付快、风险低、和现有能力叠加。**代价**：查看态交互（缩放/折叠），**不能拖拽节点/单节点配色/自由布局**。

**Phase 2（仅当明确需要"拖拽式编辑体验"时才做）= 结构化导图编辑器**
- 用户给的清单里**没有一个是干净的 React 结构化树编辑器**（Excalidraw=自由白板、
  Wisemapping=Java+webpack、draw.io=iframe 重）。诚实结论：若要真正的拖拽导图，
  需评估清单外的 React 原生库（如 `mind-elixir` / `simple-mind-map` / `react-flow`），
  或直接把 **Excalidraw 作为独立"白板"产品线**接受（好看手绘风，但不是自动布局导图）。
- 若走结构化编辑器：文档格式建议用**自有 JSON 树**（`{id,text,children,note,color}`），
  并提供 **`.mm`（FreeMind/Freeplane XML）导入/导出** 做交换（呼应桌面生态事实标准）。
- 需要新写一套 AI 工具（`add_node`/`edit_node`/`move_node`/`delete_node`/`read_tree`）。

> 一句话：**先上 Markmap（几乎零成本、AI 已就绪），把"拖拽编辑器"留到确有需求再做。**

---

## 4. Phase 1 具体集成方案（落地清单）

沿用现成 app 模式（参考 markdown app）。**不新起后端服务**，导图数据就是 `.md`。

### 4.1 渲染集成（最小方案：并入 markdown app）
- `cd frontend && npm i markmap-lib markmap-view -w @genoffice/markdown`（都是 MIT、纯浏览器，无 node 依赖，**无需 node shim**）。
- 新组件 `apps/markdown/src/renderer/mindmap/MindmapView.tsx`：
  - 用 `Transformer`(markmap-lib) 把当前编辑器的 markdown → `{root, features}`；
  - `Markmap.create(svgEl, opts, root)` 渲染；文档变更时 `mm.setData(root)+mm.fit()`。
- 在 App 顶栏加"导图视图"开关：`大纲`(现有 TipTap) / `导图`(MindmapView) / `分屏`。
- 导出：markmap-view 出的是 SVG → 直接下载 `.svg`；PNG 用 canvas 转（可选）。

### 4.2 存储 / 后端（零改动或极小改动）
- 复用 `.md` blob 与 `/documents` 版本存储：导图文件就是普通 markdown，**后端不用动**。
- 若希望 Home 里把它显示成"思维导图"类型而非 markdown：给 markdown 加约定后缀
  （如 `.mindmap.md` 或 frontmatter `type: mindmap`），在 `backend/app/routers/documents.py`
  的 `_EXT_TYPE` / 前端 Home 的类型判断里认这个约定即可（一处小改）。

### 4.3 AI 集成（零新增工具）
- 直接用 markdown app 现有 `ai/tools.ts` 的块级工具改大纲；Markmap 监听文档变化重渲。
- 可选：给 `ai/markdown-skill.ts` 的 system 追加一句"当用户要思维导图时，用**层级 Markdown
  标题/列表**组织输出"，引导 AI 产出适合导图的结构。**只改提示词，不加工具。**

### 4.4 Home 入口 / 跨应用（复用现有 handoff）
- `apps/docs/src/renderer/shell/Home.tsx`：`Kind` 增加 `'mindmap'`（脑图），`QUICK.mindmap`
  给 3~4 个示例 prompt；`goApp('markdown', prompt)` 复用现有跳转，附 `?view=mindmap` 让
  markdown app 启动即进导图视图。
- markdown app boot effect 读 `?view=mindmap` → 默认打开导图视图（对齐现有 `?gen=`/`?open=` 模式）。

### 4.5 部署 / 路由（无需新增 app 时零改动）
- 若并入 markdown app：`nginx.conf` / `Dockerfile` / `start.sh` **都不用改**（还在 3588）。
- 若坚持独立 app（不推荐，重复骨架）：才需新 workspace + 端口 3590 + nginx `/mindmap/` alias +
  静态 build + Home DEV_PORTS。**Phase 1 不做。**

### 4.6 Seed（示范内容）
- 在 `backend/app/seed/` 加一个 `mindmap-sample.md`（一份中文大纲：如"AI Office 使用地图"），
  `manifest.json` 加一条。后端无 office 库也无所谓——它就是纯文本 `.md`，直接写文件即可。

---

## 5. 风险与开放问题
- **Phase 1 的交互上限**：Markmap 是查看态交互，产品若把"能拖拽/单节点配色/自由摆位"
  当作硬需求，则 Phase 1 不够，需进 Phase 2（成本明显更高）。**先和产品确认交互预期。**
- **清单缺口**：用户给的 Web 候选里没有理想的 React 结构化导图库；Phase 2 若要做，需要引入
  清单外依赖或接受 Excalidraw 的自由白板形态。这是一个需要拍板的方向选择。
- **Mermaid 内嵌**：docs(TipTap) 里渲染 mermaid 代码块需一个 code-block 渲染扩展，属小增量，可延后。

---

## 6. 测试计划（延续 ponytail：非平凡逻辑留一个可跑校验）
- 单测：`transformer.transform(md).root` 对固定大纲断言层级/节点数（`apps/markdown/tests/mindmap.test.ts`，vitest+jsdom）。
- e2e（serve.py harness）：Home 选"脑图"→生成 → markdown app 导图视图出现 `svg .markmap g`（节点 ≥2），对齐 `e2e/tests/apps-open.spec.ts` 风格。
- 回归：markdown app 现有 `tests/doc-text.test.ts`（13）不受影响。

---

## 7. 一句话总结
**Phase 1 用 Markmap 把思维导图做成"Markdown 大纲的可交互视图"，复用 markdown app 的
存储 + AI 编辑，几乎零成本、AI 开箱即用。真正的拖拽式结构化编辑器（Phase 2）留到确有
需求再评估——而且要清楚：用户给的候选清单里并没有现成的最佳 React 结构化导图库。**
