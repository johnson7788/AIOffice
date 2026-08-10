# plan_skill.md — 支持扩展技能（skillhub.cn Skills）

## 目标
用户可以安装 https://skillhub.cn/ 上的 **Skill**（Anthropic Agent Skills 格式：一个
含 `SKILL.md` 的技能包），让 AI 助手在 5 个 app（docs/slides/sheets/pdf/markdown）里
按需调用这些技能。需要一个**技能管理界面**（安装 / 启用停用 / 删除 / 查看）。

## 关键前提：两种"skill"别搞混
- **agent-core 的 `AgentSkill`**（`packages/agent-core/src/skill.ts`）= 代码写死的能力域
  （systemPrompt + tools + executeTool）。docs/slides… 各自用 `composeSkills(...)` 把自己的
  skill 拼进 `AgentLoop`（`AiPanel.tsx:470` 等 5 处）。**这是宿主机制，不是要装的东西。**
- **skillhub 的 Skill** = `SKILL.md`（YAML frontmatter `name`/`description` + markdown 正文，
  可选 `scripts/`、`references/`）。这是**指令包 + 资源**，本质是"渐进式披露的提示词"，
  不是 TS 代码。下文称它为**扩展技能 / Skill 包**。

## 最大约束：本项目**刻意砍掉了沙箱**（见 MEMORY 架构转向）
Agent 100% 跑在浏览器 renderer；后端只做 LLM 转发 + 存储，**没有代码执行环境**。
所以：
- ✅ **能做**：把 Skill 包的 `SKILL.md` 指令 + `references/` 参考文件喂给 Agent（纯上下文）。
  这覆盖 skillhub 上**大多数偏"写作/规范/流程/知识"类技能**。
- ❌ **不能做（本期不做）**：执行 Skill 里的 `scripts/*.py|*.mjs`。那需要重新引入沙箱，
  与架构决策冲突。**S5 延后项**里单列，需要时再评估。

**结论：本期做"指令优先 + 渐进式披露"的扩展技能，脚本执行延后。**

## 设计总览
```
skillhub.cn ──(用户粘贴下载链接 / 上传 zip)──► 后端 /skills/install
                                                    │ 解析 SKILL.md、存 blob
                                                    ▼
                            [Skill 表: org 私有, enabled 开关]
                                                    │
   各 app 的 composeSkills([...appSkills, skillhubSkill]) ◄── 新增 1 个共享 AgentSkill
                                                    │
   skillhubSkill.systemPrompt = 已启用技能的 name+description 清单（渐进式披露 L0）
   skillhubSkill.tools:
     - load_skill(name)              → 返回该技能 SKILL.md 正文（L1，按需加载）
     - read_skill_file(name, path)   → 返回 references/ 下某文件文本（L2，按需加载）
```
渐进式披露 = 不把所有正文塞进系统提示（会撑爆 context）。系统提示里只放**清单**
（name+一句话 description），模型判断相关时用 `load_skill` 拉正文，需要参考资料时
再 `read_skill_file`。这正是 Anthropic Agent Skills 的原生用法，也最省 token。

## 后端（create_all-safe，无 Alembic）——沿用 Asset/Document 的既有套路
### 数据模型 `backend/app/models.py`（新增独立表）
```
Skill(
  id: str PK,
  org_id: str (idx),        # 租户隔离
  name: str,                # SKILL.md frontmatter name（唯一键用 (org_id,name)）
  description: str,         # frontmatter description（清单里展示）
  version: str | None,
  source: str,              # 'upload' | 'url:<host>' | 'skillhub:<id>'
  enabled: bool = True,     # 管理界面开关；只有 enabled 的进 Agent
  size: int,                # 包大小
  created / updated: datetime,
)
```
Skill 包（zip）存 blob：key `org/{org}/skill/{id}`（复用 `storage.py`，跟 Asset 一样）。
**独立表 = 对现有库 create_all 安全。**

### 路由 `backend/app/routers/skills.py`（prefix `/skills`，org-scoped，跨租户→404）
镜像 `routers/assets.py` 模式（Bearer 依赖、`MAX_BLOB_MB`→413、`_check_storage` 配额）：
- `GET  /skills` — 列出本 org 技能（id/name/description/version/enabled/size/source）。
- `POST /skills/upload?name=` — body=技能 zip 字节 → 解析校验 → 建 Skill（source='upload'）。
- `POST /skills/install` `{url}` — 后端下载该 zip → 同解析入库（source=`url:<host>`）。
  **skillhub 集成点**：用户从 skillhub 复制"下载链接"贴进来即可；若 skillhub 有稳定的
  按 id 下载 API，可加 `{skillhubId}` 分支拼出 URL（S2 待确认其下载 URL 格式）。
- `GET  /skills/{id}` — 详情（frontmatter + SKILL.md 正文预览 + 文件树）。
- `GET  /skills/{id}/file?path=` — 读取包内某文件文本（供前端 `read_skill_file` 走鉴权端点）。
- `PATCH /skills/{id}` `{enabled?}` — 启用/停用。
- `DELETE /skills/{id}` — 删记录 + blob。

在 `backend/app/main.py` include 该 router；`nginx.conf` 的 API 正则 + `skills`；
各 `vite.renderer.config.ts` proxy `/skills`；`e2e/serve.py` API_PREFIXES + `/skills`。

### 解析 & 校验 `_parse_skill(zip_bytes)`（纯 stdlib `zipfile` + 轻量 YAML）
- 找到 `SKILL.md`（顶层或单层子目录内），读 frontmatter（`---` 之间）取 `name`/`description`
  /`version`。frontmatter 是极简 YAML → **用 stdlib 手解析 key: value**（不引 pyyaml；
  只认这几个字段，多行 description 用引号）。缺 `name`/`description` → 400。
- 建立包内文件清单（供 `/file` 与前端展示）。
- **安全（不可简化）**：
  - **zip-slip 防护**：拒绝含 `..`、绝对路径、软链接的成员（zipfile 不解压到磁盘，只按需
    读取字节，但校验 `path` 参数不越界）。
  - 大小上限：整包 ≤ `MAX_BLOB_MB`；单文件解压上限 + 成员数上限（zip 炸弹防护）。
  - `/file` 只返回**文本类**（md/txt/json/py/mjs/csv…）且路径必须在清单内（防路径穿越）。
  - **install by URL 的 SSRF 防护**：只允许 https；禁止内网/环回/元数据 IP（169.254.*、
    10./172.16-31./192.168.、localhost）；限响应大小 + 超时；不跟随到内网的重定向。
  - **绝不执行任何脚本**：`scripts/` 仅作为文本供模型阅读，后端/前端都不 spawn。

### 配额
`upload` / `install` 过 `_check_storage`（复用 assets 的按 org 字节数逻辑，技能与图库/文档
共享 org 存储上限；要分开再说）。可加 `MAX_SKILLS_PER_ORG`（默认给个 50，0=不限）。

## 前端

### 共享扩展技能 `packages/agent-core/src/skillhub-skill.ts`（新增 1 个 AgentSkill）
> 放 agent-core 因为它是纯逻辑、5 个 app 共用；HTTP 调用通过注入的 fetch 回调，保持
> agent-core 不依赖具体 app 的 web-adapter。
```ts
export function createSkillhubSkill(api: {
  list(): Promise<{name:string; description:string}[]>          // GET /skills?enabled=1
  loadBody(name: string): Promise<string>                       // GET /skills/{id}/... 正文
  readFile(name: string, path: string): Promise<string>         // GET /skills/{id}/file
}): AgentSkill
```
- `systemPrompt`：一段固定说明 + "可用扩展技能"占位；真正清单放 `buildContext()`（每轮刷新，
  技能可能刚装）。清单格式：`- <name>: <description>`，并告诉模型"相关时先 load_skill 读正文"。
- `tools`：`load_skill{name}`、`read_skill_file{name,path}` → 调注入的 api → `ToolExecution`。
- `executeTool`：分发这两个工具。**无副作用、无沙箱**，纯读。
- 空清单（没装技能）时 `buildContext` 返回 ''、工具仍在但会返回"未找到技能" → 零噪音。

### 各 app 接线（5 处，一行）
在每个 `composeSkills('xxx+files', '', [ ...原有, createSkillhubSkill(apiForThisApp) ])`
里追加。api 的三个方法在各 app 的 `web-adapter.ts` 里实现（authFetch `/skills*`，与图库
`listAssets` 同款）。docs 的 `web-adapter.ts` 先加，其余 4 个照抄。

### 技能管理界面（复用"我的图库"那套 Home 覆盖层）
`apps/docs/src/renderer/shell/Home.tsx`：仿照 A5 的 `showGallery`：
- 侧栏在「我的图库」下方加「技能中心」按钮 → `showSkills` state。
- 覆盖层（复用 `.home-modal-backdrop/.home-modal`）里放一个**新组件**
  `packages/ui/src/SkillManager.tsx`（内联样式，零 per-app CSS，跟 ImageGallery 一样可被
  任意 app 复用）：
  - 列表：每项 name / description / version / 启用开关（PATCH enabled）/ 删除 / 查看详情。
  - 顶部：「安装」——两种入口：① 粘贴 skillhub 下载链接 → POST /skills/install；
    ② 上传 .zip → POST /skills/upload。
  - 详情：GET /skills/{id} 展示 SKILL.md 正文 + 文件树。
  - （可选）一个「浏览 skillhub」按钮 = `window.open('https://skillhub.cn/')`，用户在那边
    复制链接回来装。**不内嵌 skillhub 站内浏览**（避免耦合其页面结构）。
- ponytail：管理界面只放 docs Home 一处（登录入口就在 docs），5 个 app 的 Agent 都能用到
  装好的技能；不给每个 app 都做管理页。

## 分阶段
- **S1**：后端 `Skill` 表 + `/skills`（list/upload/get/file/patch/delete）+ `_parse_skill`
  （zipfile + 极简 frontmatter 解析）+ 安全校验（zip-slip/大小/文本白名单）。
- **S2**：`/skills/install`（URL 下载 + SSRF 防护）；确认 skillhub 的下载 URL/API 格式后
  再决定是否加 `skillhubId` 便捷分支。
- **S3**：agent-core `createSkillhubSkill` + docs `web-adapter` 三方法 + docs 接线（先跑通 1 个 app）。
- **S4**：其余 4 app 接线 + `SkillManager.tsx` + Home「技能中心」入口。
- **S5（延后，需重新评估架构）**：脚本执行沙箱（让 `scripts/*` 真正可运行）。这会引回被
  刻意移除的沙箱依赖 —— 单独立项，非本期。

## 验收 / 落地检查
- 后端：`tests/test_skills.py`——upload 一个手搓的最小技能 zip（SKILL.md + references/x.md）
  → list/get/file/patch(enabled)/delete roundtrip；缺 frontmatter→400；zip-slip 成员→拒绝；
  跨租户 404；install SSRF（内网 URL→拒绝，用 monkeypatch/mock httpx）。跟随现有 pytest 门禁。
- 前端：`createSkillhubSkill` 单测（mock api：清单进 buildContext、load_skill 返回正文、
  未知技能报错）。docs tsc + build 绿。
- e2e（可选）：登录→Home→技能中心→上传最小 zip→列表出现→停用/删除（用 `api.spec.ts`
  的确定性风格，构造最小 zip buffer；不调模型）。

## 延后项（登记，勿现在做）
- Skill 脚本执行沙箱（S5）。
- 技能版本更新/升级检查、评分/来源可信标记。
- 技能间冲突（同 name）与命名空间：本期 (org,name) 唯一即可。
- 全文搜索技能内容；按 app 类型过滤可用技能。
