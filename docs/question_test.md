# Online AI Office —— 对话式改文档测试手册（question_test.md）

侧栏发一句自然语言 → agent 调 `enqueue_office_op` 投一个结构化 op → 信箱 → 编辑器里
常驻的 `ai-bridge` 插件轮询取走 → `callCommand`(Builder API) 落到 live 会话。本文列出
**按文档类型分组的测试问题、期望 op、期望现象、验证方法**。

---

## 0. 当前测试状态（如实标注）

| 层级 | 内容 | 状态 |
|------|------|------|
| 单元 | `python -m app.office_ops` op 校验自检（含 set_cell / set_slide_text 用例） | ✅ 通过 |
| 单元 | `node --check poll.js` 插件语法 | ✅ 通过 |
| 部署 | documentserver 已服务含新 op 的 poll.js（`.gz` 已重生成） | ✅ 已确认 |
| E2E | `set_slide_background` / `replace_text` broker 全链路（headless L4） | ✅ 早前已绿 |
| E2E | **新** `set_cell` / `set_slide_text` broker 真机 | ⏳ **待测**（需先重启后端 + 无痕窗口） |

> 下表每条用例都标了「验证状态」，⏳ = 尚未真机跑过，需按本手册验证。

---

## 1. 前置条件（每次真机测试前）

1. **重启后端**——改了 `office_ops.py` / `tools.py`，新 op 才进 agent 工具（`./start.sh` 里的后端）。
2. **documentserver 在跑**：`curl -s localhost:8081/healthcheck` → `true`。
3. **用无痕窗口**开 http://localhost:3585/ —— 普通窗口的 service worker 会缓存旧插件注册表，
   导致 `ai-bridge` 不 autostart（已确诊的坑）。无痕 = 全新上下文，插件正常轮询。
4. **在编辑器里真正打开目标文件**（不是只在文件树里选中）——op 应用在「当前 live 会话打开的那份文档」上。
5. 打开后**等约 5 秒**让插件 autostart 起轮询，再发指令。

> ⚠️ **op 不带编辑器身份**：信箱里的 op 会落到当前打开的**任意**文档上。测 xlsx 的 `set_cell` 前，
> 确保编辑器里开的是 xlsx；开着 pptx 发 `set_cell` 会静默 no-op（agent 一般会按文件后缀自选正确 op）。

---

## 2. 通用验证手段

```bash
# ① 看信箱里 op 是否被取走（发指令后立刻 curl；若 op 一直 survive = 插件没轮询 = 见前置条件 3）
curl -s "http://localhost:8585/office/pending?user_id=default_user"
#   期望：发完指令几秒内变回 {"ops":[]}（被插件取走）。若一直有 op = 没 poller。

# ② 浏览器控制台（无痕窗口 DevTools Console）应打印：
#   [ai-bridge] applyOp {"type":"set_cell",...}
#   [ai-bridge] callCommand done

# ③ 落盘验证（改动先在 live 会话可见；落盘需 Ctrl+S 或关闭编辑器触发 forcesave→callback）
UP=/Users/admin/git/skill-ppt-agents/backend/uploads/default_user

# pptx 第 N 页背景色（1-based 页号→脚本里 slideN.xml）
python3 -c "import zipfile,re;x=zipfile.ZipFile('$UP/LongContextLLM.pptx').read('ppt/slides/slide1.xml').decode();m=re.search(r'<p:bg>.*?srgbClr\s+val=.([0-9A-Fa-f]{6})',x,re.S);print(m.group(1).upper() if m else 'NONE')"

# xlsx 单元格值（需 openpyxl；用后端 venv）
cd /Users/admin/git/skill-ppt-agents/backend && .venv/bin/python -c "import openpyxl;wb=openpyxl.load_workbook('$UP/2-日常费用报销单2.xlsx');print(wb.active['B2'].value)"

# docx 是否含某词
unzip -p "$UP/基础研究的元素（prompt）.docx" word/document.xml | grep -o "新词" | head
```

---

## 3. 测试用例矩阵

图例：**输入** = 侧栏发的自然语言；**期望 op** = agent 应投递的 JSON；**期望现象** = 编辑器里肉眼所见。

### 3.1 演示文稿 PPTX（打开 `LongContextLLM.pptx`）

| # | 输入指令 | 期望 op | 期望现象 | 验证 | 状态 |
|---|----------|---------|----------|------|------|
| P1 | 把第一页背景改成红色 | `{"type":"set_slide_background","slide":0,"color":"#FF0000"}` | 第 1 页立即变红 | 手段①②③(bg) | ✅ 早前绿 |
| P2 | 把第 2 页背景改成天蓝色 | `set_slide_background, slide:1, #87CEEB` | 第 2 页变天蓝 | 同上（slide2.xml） | ✅ 早前绿 |
| P3 | 把第一页的标题改成「长上下文综述」 | `{"type":"set_slide_text","slide":0,"shape":0,"text":"长上下文综述"}` | 第 1 页首个形状(标题)文字被替换 | 手段①② + 打开看 | ⏳ 待测 |
| P4 | 把第一页第二个文本框内容改成「作者：张三」 | `set_slide_text, slide:0, shape:1, text:"作者：张三"` | 第 1 页第 2 个形状文字变化 | 同上 | ⏳ 待测 |

> 说明：`shape` 从 0 起，通常 0=标题。哪个 shape 对应哪块要看具体模板，测时先试 0/1 观察。

### 3.2 电子表格 XLSX（打开 `2-日常费用报销单2.xlsx`）

| # | 输入指令 | 期望 op | 期望现象 | 验证 | 状态 |
|---|----------|---------|----------|------|------|
| X1 | 把 B2 单元格填成 42 | `{"type":"set_cell","cell":"B2","value":"42"}` | B2 显示 42 | 手段①② + openpyxl 读 B2 | ⏳ 待测 |
| X2 | 在 A1 写「报销汇总」 | `set_cell, cell:"A1", value:"报销汇总"` | A1 显示该文本 | 同上（读 A1） | ⏳ 待测 |
| X3 | 把 C5 填成 =SUM(C1:C4) | `set_cell, cell:"C5", value:"=SUM(C1:C4)"` | C5 显示求和结果 | 引擎按公式解析 | ⏳ 待测 |
| X4 | 把 A1:C1 都填成「表头」 | `set_cell, cell:"A1:C1", value:"表头"` | 该区域每格都是「表头」 | 读多格 | ⏳ 待测 |

> `value` 恒为字符串投递；数字/公式（以 `=` 开头）由 ONLYOFFICE 引擎按单元格格式自行解析。

### 3.3 文档 DOCX（打开 `基础研究的元素（prompt）.docx`）

| # | 输入指令 | 期望 op | 期望现象 | 验证 | 状态 |
|---|----------|---------|----------|------|------|
| W1 | 把全文的「基础研究」替换成「基础科研」 | `{"type":"replace_text","find":"基础研究","replace":"基础科研"}` | 全文所有「基础研究」变「基础科研」 | 手段①② + grep document.xml | ✅ 机制早前绿 |
| W2 | 把「prompt」都改成「提示词」 | `replace_text, find:"prompt", replace:"提示词"` | 全文替换 | 同上 | ⏳ 待测该文件 |

### 3.4 选区改写（通用，走**可视面板**而非侧栏）

`replace_selection` 需要选区上下文，**不走侧栏 broker**，走编辑器工具栏「AI 改写」插件面板：

| # | 操作 | 期望 op | 期望现象 | 状态 |
|---|------|---------|----------|------|
| S1 | 选中一段文字 → 开「AI 改写」面板 → 输入「改得更正式」 | `{"type":"replace_selection","text":"...改写后..."}` | 选区被替换为 LLM 改写结果 | ✅ L3 绿 |

---

## 4. 边界 / 负例（应「优雅拒绝」而非崩溃）

| # | 输入 / 场景 | 期望 |
|---|-------------|------|
| N1 | 「把第一页背景改成大红色」（非 #RRGGBB，agent 需自行转成 #RR..） | agent 转出合法 hex；若传 `color:"red"` → `parse_office_op` 抛 ValueError → 工具返回 `{"error":"color 必须是 #RRGGBB"}` |
| N2 | 「把 ZZ 单元格填成 1」（非法引用，无行号） | `{"error":"cell 必须是 A1 或 A1:B2 形式的引用"}` |
| N3 | 开着 **pptx** 却发「把 B2 填成 5」 | agent 应按后缀避免；即便投了 `set_cell`，插件在 slide 编辑器里 `Api.GetActiveSheet` 不存在 → 静默 no-op（不崩） |
| N4 | 「帮我把这张图裁剪一下」（超出当前 op 集） | agent 应**如实说不支持**（instruction 铁律），不得臆造/乱投 op |
| N5 | 「把第 99 页背景改红」（页不存在） | `GetSlideByIndex(98)` 返回 null → 插件 `if(oSlide)` 跳过 → 无效果、不崩 |

---

## 5. 落盘说明（重要，别误判"没生效"）

- `callCommand` **只改 live 会话**，改动**立即在编辑器里可见**——这就是主要目标。
- **落盘到磁盘**沿用 P2：需 **Ctrl+S**（标记待保存）或**关闭编辑器**触发 documentserver `forcesave`
  → `POST /office/callback` 写回 `uploads/<user_id>/`。
- 所以：**看编辑器画面**判断 op 是否生效（手段②控制台日志最准）；**读磁盘文件**判断是否已落盘。
  两者时机不同，别把"live 已变、磁盘未落"误判成失败。

---

## 6. 一句话冒烟测试（最快确认链路活着）

无痕开 xlsx → 等 5s → 侧栏发「把 B2 填成 42」→ 控制台出现 `[ai-bridge] applyOp {set_cell...} → callCommand done`
→ B2 显示 42。三者齐 = 新 op 全链路通。
