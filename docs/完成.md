# 在线办公 + Skills 智能体 集成计划

把 ONLYOFFICE（在线看/改 doc/xls/ppt/pdf + 目录树）和 Excalidraw（思维导图/白板）
接进现有「每用户一个沙箱 + Skills 智能体」的架构。

## 0. 现状（集成的地基，别重造）

| 部分 | 现状 | 复用点 |
|------|------|--------|
| 后端 | FastAPI + Google ADK，端口 8585，SSE 流式对话 | 直接加路由 |
| 沙箱 | 每用户独占 OpenSandbox，`_sbkey = user_id`（`backend/app/sandbox.py`） | 文件都存这，天然多租户隔离 |
| 沙箱文件 API | `files.list_directory` / `get_file_info` / `write_file(s)` 已有 | **缺一个 read/download，需补** |
| Skills | ADK `SkillToolset`，Agent 把产物写进沙箱 | 产物自动出现在文件树，能被编辑器打开 |
| 上传/下载 | 落本地 `uploads/<user_id>/`（`server.py` 已标 TODO 要转沙箱） | 统一改成走沙箱 |
| 前端 | React 19 + Vite + Tailwind + lucide，单页聊天 | 加「文件树 + 编辑器」面板 |

结论：**沙箱就是每个用户的"网盘"根目录**。办公套件和白板都只是这个目录上的两种查看器，不引入第二套存储。

## 1. 目标架构

```
┌── 前端 (Vite:3585) ─────────────────────────────┐
│  聊天面板  │  文件树  │  ONLYOFFICE iframe        │
│           │         │  / Excalidraw 组件         │
└──────┬─────────┬───────────────┬─────────────────┘
       │ SSE     │ REST 文件API   │ 编辑器 config/回写
       ▼         ▼                ▼
┌── 后端 FastAPI (8585) ──────────────────────────┐
│  /chat/stream  /files/*   /office/*(网关+JWT)   │
└──────┬──────────────────────┬────────────────────┘
       │ sandbox.files.*       │ HTTP 拉取/回写
       ▼                       ▼
   每用户 OpenSandbox      ONLYOFFICE DocumentServer
   (文件真身在这)          (独立 Docker 容器)
```

- **Excalidraw**：纯前端组件，读写沙箱里的 `.excalidraw` JSON，不碰 DocumentServer。
- **ONLYOFFICE**：DocumentServer 是独立容器，只认 HTTP URL。文件在远程沙箱里，
  所以**后端必须当文件网关**：给 DocServer 一个下载 URL，收它的保存回调再写回沙箱。

## 2. ONLYOFFICE 集成（doc/xls/ppt/pdf）

用社区版镜像 `onlyoffice/documentserver`（免费，~20 并发连接，够用）。

### 2.1 部署
docker-compose 加一个服务：
```yaml
  documentserver:
    image: onlyoffice/documentserver
    environment:
      - JWT_ENABLED=true
      - JWT_SECRET=${OFFICE_JWT_SECRET}   # 与后端共享，安全边界，必须开
    ports: ["8080:80"]
```
DocServer 与后端要能互相通过内网 URL 访问（compose 同网络即可）。

### 2.2 编辑器嵌入（前端）
1. 加载 `http://<docserver>/web-apps/apps/api/documents/api.js`
2. `new DocsAPI.DocEditor("ph", config)`，config 由**后端签发**（前端不持有 JWT 密钥）。
3. 后缀 → documentType 映射：`.docx→word` `.xlsx→cell` `.pptx→slide` `.pdf→pdf`
   （pdf 编辑需 DocServer ≥ 7.x）。

### 2.3 后端三个网关端点（新增，都带 JWT）
| 端点 | 作用 |
|------|------|
| `GET /office/config?path=` | 读沙箱文件信息 → 返回**签名后**的 DocEditor config（含 document.url、document.key、callbackUrl、token） |
| `GET /office/download?token=` | DocServer 来拉原文件：校验 JWT → `sandbox.files` 读字节流回去 |
| `POST /office/callback?token=` | DocServer 保存回调：`status==2` 时下载编辑后文件 → `sandbox.write_file` 写回沙箱 |

关键点（踩坑预防）：
- `document.key`：**同一文件同一版本必须稳定、改动后必须变**，否则编辑器显示缓存旧内容。
  用 `md5(path + mtime)` 生成。
- config 的 `token` 用 `OFFICE_JWT_SECRET` 签；callback 也带 token，**必须验签**再落盘。
- `download`/`callback` 的 URL 里的 host 必须是 DocServer 容器能访问到的后端地址（内网名，不是 localhost）。

## 3. Excalidraw 集成（思维导图/白板）

纯前端，最省事的一块。

1. `npm i @excalidraw/excalidraw`（含思维导图/白板全部能力）。
2. `<Excalidraw initialData={scene} onChange={debounced(save)} />`。
3. 打开：`GET /files/raw?path=x.excalidraw` → `JSON.parse` → initialData。
4. 保存：序列化 `{elements, appState, files}` → `PUT /files/raw`（写回沙箱）。
5. 思维导图/流程图：`@excalidraw/mermaid-to-excalidraw` 把 mermaid 转成 excalidraw 元素，
   Skill 可以直接产出 mermaid，前端转成可编辑白板。

## 4. 文件树 / 目录（两个编辑器共用）

沙箱就是根目录，直接包 `sandbox.files.list_directory`。

新增文件 API（`backend/app/`，比如 `files_api.py`）：
| 端点 | 实现 |
|------|------|
| `GET  /files/tree?path=` | `sandbox.files.list_directory(depth=1)`，前端懒加载展开 |
| `GET  /files/raw?path=`  | 读字节流（Excalidraw/预览/office-download 共用同一读函数） |
| `PUT  /files/raw?path=`  | `sandbox.write_file`（Excalidraw 保存、上传落盘） |
| `DELETE /files?path=`    | 删除 |
| `POST /files/upload`     | 改现有 `/upload`：不落本地，直接写沙箱 |

**前置补丁**：`sandbox.py` 目前只有 `write_file`，没有读。加一个
`read_file(key, path) -> bytes`（`sandbox.files` 的下载/读接口），office 网关和文件 API 都依赖它。

## 5. 与 Skills 智能体的结合点

不用改 Skills 机制，只是打通"产物 ↔ 编辑器"：

- Agent 生成的 `.pptx / .docx / .xlsx / .excalidraw` 写进沙箱 → 文件树里出现 → 点开即用对应编辑器改。
  现有 `dashi-ppt` / `ppt-deck` 产出的 pptx 立刻能在 ONLYOFFICE 里二次编辑。
- 反向：编辑器里改完存回沙箱 → 用户可以让 Agent「基于我刚改的 X.pptx 继续…」，
  Agent 用 `terminal`/`run_skill_script` 读同一份沙箱文件。
- 可选新增 Skill：`docx-gen`（python-docx）、`xlsx-gen`（openpyxl）、`mindmap`（产 mermaid→excalidraw），
  让 Agent 能直接生成这四类可编辑文档。—— 按需再加，先别写。

## 6. 前端改动

- App.tsx 布局改三栏：聊天 | 文件树 | 编辑区（编辑区按后缀路由到 ONLYOFFICE iframe 或 Excalidraw）。
- 新组件：`FileTree.tsx`、`OfficeEditor.tsx`（iframe + DocsAPI）、`WhiteboardEditor.tsx`（Excalidraw）。
- 依赖只加 `@excalidraw/excalidraw`（+ 可选 mermaid-to-excalidraw）；ONLYOFFICE 走 CDN/自托管 script，不进 npm。

## 7. 安全（不能偷懒的地方）

- ONLYOFFICE JWT 全程开启，config 后端签、callback 后端验；密钥只在后端。
- 所有 `/files/*`、`/office/*` 端点按 `user_id` 定位沙箱，**路径做规范化**防 `../` 越权（现有 `/download` 已有 `resolve()+startswith` 校验，复用同一套）。
- DocServer download/callback URL 用不可猜的短期 token（JWT，绑 path + 过期），别用明文路径直连。

## 8. 分阶段落地

1. **P0 文件底座** ✅：`/files/tree|raw`(GET/PUT) + `/files`(DELETE)，前端 `Workspace.tsx` 文件树+预览。
   —— 决策修正：文档空间用**本地 uploads/<user_id>/**（产物/下载已在这），沙箱仍是代码执行环境，没接 `sandbox.read_file`。
2. **P1 Excalidraw** ✅：装 `@excalidraw/excalidraw@0.18`，`WhiteboardEditor.tsx` 读写 `.excalidraw`（走 /files/raw，防抖保存）。
   思维导图/流程图用 Excalidraw 自带的 mermaid→excalidraw，无需额外依赖。
3. **P2 ONLYOFFICE** ✅（代码就绪，待起容器端到端验证）：
   - docker-compose 加 `documentserver`（端口 8081，8080 被 OpenSandbox 占）+ JWT。
   - 后端网关 `/office/config`(签发)、`/office/download`(DocServer 拉)、`/office/callback`(写回)，PyJWT 签验。
   - 前端 `OfficeEditor.tsx` 加载 api.js 嵌 DocEditor；未配置时回退下载。pdf 也走 ONLYOFFICE。
   - env：`OFFICE_JWT_SECRET/OFFICE_PORT/OFFICE_DOCSERVER_URL/OFFICE_BACKEND_URL`。
   - 端到端验证：`docker compose up -d documentserver` 后，工作台打开 .docx/.pptx 编辑保存回写。
4. **P3 Skills 联动** ✅：加 `save_to_workspace` 工具（app/tools.py），Agent 把 Markdown/CSV/JSON/HTML/SVG/mindmap(.md) 等文本产物写进本地 `uploads/<user_id>/`，
   自动出现在工作台文件树，点开即用 ONLYOFFICE/Excalidraw 编辑。已注册进 agent.py，instruction.md 加说明，server.py 加友好名。
   PPT 仍走 `generate_ppt`。docx/xlsx（需 python-docx/openpyxl）、mermaid→excalidraw 思维导图 skill 按需再加。
   —— 补充：思维导图/架构图已接 `excalidraw-diagram` skill（Agent 手写 `.excalidraw` JSON，复用 WhiteboardEditor 可编辑，跳过 chromium 渲染校验）。

---

## 9. P4 —— 界面商务化改版（TODO）

**问题**：当前是"开发者工具风"，不够正式/友好。具体病灶（对照代码）：

| # | 病灶 | 位置 |
|---|------|------|
| 1 | 两条顶栏 + 两个 userId 入口冗余 | Shell tab 栏 `main.tsx:14` + Header 面包屑 `App.tsx:148`，各带一个 userId 编辑框（`main.tsx:33`/`App.tsx:155`） |
| 2 | userId 是裸输入框，很"demo" | `main.tsx:33` |
| 3 | 文案没跟上改名：输入框 placeholder 仍是「输入你的研究问题…」（arxiv 遗留） | `App.tsx:1277` |
| 4 | PPT 模版下拉常驻输入行，Word/Excel/思维导图时是噪音 | `App.tsx:1254` |
| 5 | 深黑霓虹蓝配色（`#0a0e1a`/`bg-blue-600`）= AI dev tool 味 | 全局 |
| 6 | 空状态单薄 + 彩色药丸 chips，缺分组与层次 | `App.tsx:1126`/`1133` |

**方向**：选 **A 浅色企业级 SaaS 风**（白/浅灰底、中性灰正文、单一品牌蓝点缀、卡片化引导、系统中文字体栈）；备选 B 精致深色（改动小、天花板低）。

**落地优先级**（高杠杆→锦上添花）：
1. 合并两条顶栏为一条（logo+产品名 · tab · 用户菜单），userId 收进用户菜单。
2. 统一文案：placeholder → 「描述你想生成的内容，如：把季度业绩做成 Excel 表格」。
3. 模版下拉移出输入行（放"高级选项"或按意图动态显示）。
4. 空状态改分组能力卡（PPT / 文档 / 表格 / 图，各带图标+一句说明）。
5. 整体换色（选 A 则系统性替换配色）。

> 先做 1/2/3（不动配色、见效快），验收后再决定 4/5。**注意 P4 的顶栏合并要和 P5 的三栏布局一起规划，别改两遍。**

## 10. P5 —— 对话即编辑：合并「对话」与「工作台」（进行中）

> **进度**：10.3 的 1（布局合并+顶栏）✅、2（文档感知）✅、3（白板对话式编辑）✅ 已落地。
> 4（ONLYOFFICE 选区编辑）**方案已改**：Connector API 是付费 Developer Edition 独有，免费社区版拿不到 → 改走**免费的 ONLYOFFICE 插件（Plugin）**路径（详见 §10.4），待 POC；5（图片重绘）依赖尚不存在的 image skill，未做。
> **白板方案实际落地与 10.2 原设计不同**：不做"选区→LLM 返回局部 elements"（DeepSeek 手写合法 excalidraw 元素 JSON 不稳，且 agent 无读回白板的工具）。改为**整图重画+自动重载**：前端 sendMessage 把当前 `.excalidraw` 完整 JSON 注入消息 → agent 用 excalidraw-diagram 技能产出整份新场景 → `save_to_workspace(同名路径, 新JSON)` 覆盖 → 前端回合结束触发 `onDocChanged` → Shell `reloadNonce+1` → Workspace 用 `key=path:nonce` 重挂 WhiteboardEditor 重新 readFileText。零后端改动，复用现有 skill+save_to_workspace。代价：丢用户手动布局、非选区级、每次整图。


**动机**：希望用户打开文件后，能用对话对**某个段落/某张图**做编辑。一旦助手"文档感知"，独立对话页就与工作台重复——**合并成单页**。

### 10.1 目标布局（替换现在的两个顶层 tab）

```
┌ 顶栏: logo · 产品名 · 用户菜单 ───────────────────────────┐
├───────────┬─────────────────────────────┬───────────────┤
│ 文件树 /  │   主区 = 编辑器              │  助手侧栏     │
│ 会话      │   (ONLYOFFICE / 白板 / 预览  │  (对话，可折叠)│
│           │    或 无文件时 = 生成首页)   │               │
└───────────┴─────────────────────────────┴───────────────┘
```

- **无打开文件** → 主区 = 生成首页（现欢迎页能力卡）；助手 = 通用生成对话（现有 `/chat/stream`）。产物生成后进文件树并在主区自动打开。
- **打开文件** → 主区 = 对应编辑器；助手切成"文档助手"，作用域绑定当前文件。
- 一套 SSE 通道两种用途：整篇生成 vs 选区改写。助手不再是独立页，而是**随主区上下文切作用域的常驻侧栏**——这正是去重的关键。

### 10.2 选区 → 对话 → 回写（按编辑器分）

**总原则：LLM 只产"替换内容"，实际写回由前端编辑器 API 做**，后端不直接改 office 二进制（避免与 DocServer 抢写坏格式）。

| 编辑器 | 读选区 | 回写 |
|--------|--------|------|
| **Excalidraw**（白板/思维导图） | `excalidrawAPI.getSceneElements()` + `appState.selectedElementIds` | LLM 返回新 elements → `updateScene({elements})` 局部替换 → 现有防抖 PUT 保存 |
| **ONLYOFFICE**（docx/xlsx/pptx） | **免费 Plugin** 内 `window.Asc.plugin.executeMethod("GetSelectedText")` 读选区（**非**付费 Connector） | 同一插件 `executeMethod("PasteText", [新文本])` / `callCommand` 替换选区 → ONLYOFFICE 自身 callback 落盘（沿用 P2）。**仅可编辑文档，pdf 只读** |
| **图片文件**（png/jpg 预览） | 整图或框选区域 | vision 理解 + image 模型重绘 → 替换文件 |

**后端**：新增"选区改写"入口（复用 `/chat/stream` 带 `context`，或新 `/chat/edit`）：
入参 `{file_path, selection:{type:text|image|elements, content, locator}, instruction}` → 出参"替换内容"（text / new elements / image url）。落盘仍走 office callback（P2）或白板防抖 PUT。

### 10.3 分步落地（建议顺序）

1. **布局合并**：Shell 从 tab 切换 → 三栏常驻；把 App.tsx 的对话逻辑抽成 `AssistantPanel`，主区抽成 `EditorPane`（按后缀路由）。**与 P4 顶栏合并同批做。**
2. **文档感知**：主区打开文件时，把 `{当前文件, 编辑器类型}` 注入助手上下文，首屏提示"可以让我改这份文档的某段/某图"。
3. **白板选区编辑先行**（最简单，excalidrawAPI 现成）：选中节点 → 指令 → `updateScene`，跑通"选区→对话→回写"闭环。
4. **ONLYOFFICE 选区编辑（走免费 Plugin，详见 §10.4）**：Connector 付费拿不到 → 写社区版免费插件读/写选区。分 POC→接 LLM 两步。
5. **图片重绘**（依赖 image skill）。

**风险/备注**：
- ONLYOFFICE 社区版 **Connector**（宿主页遥控）付费独有，改用免费 **Plugin**（编辑器内）；Plugin 的 `callCommand`/`PasteText` 写回需在我们这个 community docker 构建上先 POC 实测生效。
- 三栏窄屏拥挤 → 助手侧栏与文件树都做成可折叠。
- P4 与 P5 的顶栏是同一块，务必一起改，避免返工。

### 10.4 ONLYOFFICE 免费插件方案（替代付费 Connector）——实施计划

**为什么走插件**：宿主页 Connector API（`docEditor.createConnector`/`executeMethod`/`callCommand`）是付费
Developer Edition 独有；但 **ONLYOFFICE 插件（Plugin）系统在社区版完全开放免费**，插件跑在编辑器
iframe 内，`window.Asc.plugin.executeMethod("GetSelectedText")` 读选区 + `executeMethod("PasteText",[…])`/
`callCommand` 写回选区，能力等同 Connector（Connector 本质=把同一套 Plugin API 暴露给宿主页的付费封装）。
官方自带 Translator 插件即「读选区→翻译→写回」范例，证明社区版可行。

**插件形态**（一个静态目录，挂进 DocServer 容器）：
```
backend/office_plugin/ai-rewrite/
  config.json     # guid/name/按钮/variations；声明 isViewer:false、editorsSupport
  index.html      # 插件面板 UI：一个指令输入框 + 「改写」按钮
  code.js         # window.Asc.plugin.init / button 事件；读选区→fetch 后端→PasteText 写回
  icons/*         # 工具栏图标
```
容器挂载：compose 给 documentserver 加
`volumes: ["./backend/office_plugin/ai-rewrite:/var/www/onlyoffice/documentserver/sdkjs-plugins/ai-rewrite"]`
（社区版插件自动发现该目录；改 config 后可能要重启容器）。

**后端新增一个无状态端点**（复用现有 DeepSeek 客户端）：
`POST /office/edit  {text, instruction} -> {text: 改写后}`。纯文本进出、不碰文件二进制、不需 user_id/path
（回写由插件在编辑器内做，落盘沿用 P2 的 office callback）。注意 CORS：插件 iframe 来自 DocServer 源，
fetch 到 8585 要允许跨域（给该端点加 CORS，或走 `OFFICE_BACKEND_URL`）。

**分步 POC（先证链路，再接智能）**：
1. **P-a 写回验证（零 LLM）**：插件读选区 → 直接 `PasteText("【已改写】"+原文)` 写回。
   目的：**在我们这个 community docker 构建上实测 `executeMethod`/`callCommand` 写回真的生效**（这是唯一没把握的点）。
2. **P-b 接 LLM**：插件面板输入指令 → `POST /office/edit{选区文本, 指令}` → DeepSeek 改写 → `PasteText` 写回 → 用户 Ctrl+S/自动 forcesave 触发 P2 callback 落盘。
3. **P-c（可选，锦上添花）**：把「指令输入」从插件自带面板桥接到右侧助手侧栏（跨 iframe `postMessage`），
   让 office 编辑和白板编辑共用同一个助手对话框，体验统一。POC 阶段先用插件自带面板，不做 postMessage。

**边界**：仅 docx/xlsx/pptx 可写，pdf 只读；选区改写是「替换选中文本」粒度，复杂格式（表格结构、图片）不在 POC 范围。
**待确认（POC 要打勾的）**：① 插件目录挂载后编辑器工具栏能出现按钮；② `GetSelectedText` 拿到选区；
③ `PasteText`/`callCommand` 写回生效且 P2 callback 正常落盘；④ 插件 iframe fetch 后端的跨域放行。
