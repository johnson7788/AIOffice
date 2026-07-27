import { test, expect } from "@playwright/test";
import { execSync } from "node:child_process";

// L4 broker 桥全链路：开 pptx → 后台常驻插件(background.html/poll.js)autostart 轮询 →
// 从 node 走 /chat/stream（正是助手侧栏做的）发"改第一页背景为 #TARGET" →
// agent 调 enqueue_office_op 投信箱 → 插件轮询取走 callCommand SetBackground →
// Ctrl+S + 断开 → forcesave → callback 落盘 → 断言磁盘背景 == TARGET。
// 与 L3 的区别：不手动开插件面板，验证的是「侧栏 → 后端信箱 → 后台插件」这条新管道。
const FILE = "循证医学智能体.pptx";
const PPTX = `/Users/admin/git/skill-ppt-agents/backend/uploads/default_user/${FILE}`;
const DOCHINT = `\n\n[当前正在工作台编辑文件: ${FILE}（路径 ${FILE}），若用户的修改请求针对该文件，请对其内容操作]`;

function bg(): string {
  return execSync(
    `python3 -c "import zipfile,re;x=zipfile.ZipFile('${PPTX}').read('ppt/slides/slide1.xml').decode();m=re.search(r'<p:bg>.*?srgbClr\\s+val=.([0-9A-Fa-f]{6})',x,re.S);print(m.group(1).upper() if m else 'NONE')"`
  ).toString().trim();
}

// 助手侧栏等价物：POST /chat/stream，读到流结束（agent 在收尾前已调 enqueue_office_op）
async function sidebarSend(message: string) {
  const r = await fetch("http://localhost:8585/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, user_id: "default_user" }),
  });
  await r.text(); // 读完整个 SSE 流
}

test("侧栏指令经 broker 信箱 → 后台插件落盘生效", async ({ page }) => {
  test.setTimeout(180_000);
  const before = bg();
  console.log("改前背景:", before);

  await page.goto("/");
  await page.getByText(FILE, { exact: false }).first().click();
  await page.waitForTimeout(10_000); // 等编辑器加载 + 后台插件 autostart 起轮询

  const ed = page.frame({ name: "frameEditor" });
  expect(ed, "拿到编辑器 iframe").toBeTruthy();

  const TARGET = (0x100000 + Math.floor(Math.random() * 0xefffff)).toString(16).toUpperCase().slice(-6);
  expect(TARGET, "随机目标色须不同于初始色").not.toBe(before);

  // 走后端 /chat/stream（= 侧栏），让 agent 把 op 投进信箱
  await sidebarSend(`把第一页背景改成 #${TARGET}` + DOCHINT);
  console.log("已发送侧栏指令，目标色:", TARGET);

  // 等后台插件轮询(2s)取走并 callCommand 应用
  await page.waitForTimeout(6000);

  // 触发落盘：聚焦画布 → Ctrl+S 标记待保存 → 断开连接 → forcesave → callback 写 uploads
  await page.mouse.click(600, 400);
  await page.keyboard.press("Control+s");
  await page.waitForTimeout(3000);
  await page.context().close();

  let after = before;
  for (let i = 0; i < 60; i++) {
    after = bg();
    if (after === TARGET) break;
    await new Promise((r) => setTimeout(r, 1500));
  }
  console.log("改后背景:", after, "目标:", TARGET);
  expect(after, "背景色应经 broker 桥落盘为目标色").toBe(TARGET);
});
