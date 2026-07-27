import { test, expect } from "@playwright/test";
import { execSync } from "node:child_process";

// L3 全链路：文件树开 pptx → 编辑器「AI 改写」插件 → 填指令 → 执行(callCommand SetBackground)
// → Ctrl+S(forcesave→callback) → 断言 uploads 磁盘上的幻灯片背景色真的变了。
// 前置：backend:8585 + frontend:3585 + documentserver:8081(挂 ai-rewrite 插件) 都在跑。
const FILE = "循证医学智能体.pptx";
const PPTX = `/Users/admin/git/skill-ppt-agents/backend/uploads/default_user/${FILE}`;

function bg(): string {
  // 复用 docs/端到端测试.md §3 的断言逻辑，读 slide1 的 <p:bg> 色
  return execSync(
    `python3 -c "import zipfile,re;x=zipfile.ZipFile('${PPTX}').read('ppt/slides/slide1.xml').decode();m=re.search(r'<p:bg>.*?srgbClr\\s+val=.([0-9A-Fa-f]{6})',x,re.S);print(m.group(1).upper() if m else 'NONE')"`
  ).toString().trim();
}

test("自然语言改幻灯片背景 → 落盘生效", async ({ page }) => {
  test.setTimeout(120_000);
  const before = bg();
  console.log("改前背景:", before);

  await page.goto("/");
  await page.getByText(FILE, { exact: false }).first().click();
  await page.waitForTimeout(8000); // 等编辑器加载文档

  const ed = page.frame({ name: "frameEditor" });
  expect(ed, "拿到编辑器 iframe").toBeTruthy();

  // 先切到「插件」选项卡，插件按钮才显示；再点「AI 改写」打开面板
  await ed!.getByText(/^插件$|Plugins/).first().click();
  await page.waitForTimeout(1500);
  await ed!.getByText(/AI\s*改写/).first().click();
  await page.waitForTimeout(3000);

  // 找到插件自身的 iframe（含我们 index.html 的 #inst 输入框）
  let plugin = null as import("@playwright/test").Frame | null;
  for (let i = 0; i < 20 && !plugin; i++) {
    for (const f of page.frames()) {
      if (await f.locator("#inst").count().catch(() => 0)) { plugin = f; break; }
    }
    if (!plugin) await page.waitForTimeout(500);
  }
  expect(plugin, "拿到插件面板 iframe").toBeTruthy();

  // 每次用随机目标色，断言磁盘精确变成它（保证与初始态不同，真区分度）
  const TARGET = (0x100000 + Math.floor(Math.random() * 0xefffff)).toString(16).toUpperCase().slice(-6);
  expect(TARGET, "随机目标色须不同于初始色").not.toBe(before);
  await plugin!.locator("#inst").fill(`把第一页背景改成 #${TARGET}`);
  await plugin!.locator("#go").click();

  // 等状态出现「已应用」
  await expect(plugin!.locator("#status")).toContainText(/已应用|已替换/, { timeout: 40_000 });
  console.log("插件状态:", await plugin!.locator("#status").innerText());

  // 触发落盘：Ctrl+S 把 live 改动标记为待保存，再关 context 断开 → documentserver forcesave → callback 写回 uploads。
  // （callCommand 只改 live 模型，落盘依赖 ONLYOFFICE 保存/断开机制，这一步验证的正是「管道」。）
  await page.mouse.click(600, 400); // 聚焦编辑器画布
  await page.keyboard.press("Control+s");
  await page.waitForTimeout(3000);
  await page.context().close();

  // poll 磁盘直到背景色变成目标色（断开→callback 有延迟，给足 90s）
  let after = before;
  for (let i = 0; i < 60; i++) {
    after = bg();
    if (after === TARGET) break;
    await new Promise((r) => setTimeout(r, 1500));
  }
  console.log("改后背景:", after, "目标:", TARGET);
  expect(after, "背景色应精确落盘为目标色").toBe(TARGET);
});
