import { expect, test, type Page } from '@playwright/test'
import { registerViaUi } from './helpers'

// The slides agent may ask a clarifying questionnaire before generating the
// deck. Answer each question with its first option: single-selects auto-advance,
// multi-selects expose a foot next-arrow, and the last question shows submit.
async function answerClarify(page: Page): Promise<void> {
  for (let i = 0; i < 20; i++) {
    const first = page.locator('.ai-clarify-opt').first()
    if (await first.isVisible()) await first.click()
    const next = page.locator('.ai-clarify-next')
    if (await next.isVisible()) {
      await next.click()
      continue
    }
    const submit = page.locator('.ai-clarify-submit')
    if (await submit.isVisible()) {
      await submit.click()
      return
    }
    await page.waitForTimeout(200)
  }
}

// AI generation for each file type, driven from the docs Home composer. These
// hit the real model (MODEL_PROVIDER/MODEL_NAME + <PROVIDER>_API_KEY in .env),
// so they are slow and model-dependent. Serialized: concurrent agent runs would
// just contend for one model key.
//
// Completion signals per app:
//   docs   → the agent streams the generated doc into the ProseMirror editor
//   slides → generate_deck builds pages, each rendering a thumbnail
//   sheets → the auto-save on run-completion persists the workbook to the
//            backend (POST /documents) — verify via the recent-docs API, since
//            the status-bar 已保存 is transient (the save reloads the workbook
//            and the load-complete message overwrites it)
test.describe.configure({ mode: 'serial' })

test('generate a Word document from the Home composer', async ({ page }) => {
  await registerViaUi(page)
  await page.locator('.home-input').fill('写一份简短的人工智能介绍，包含标题和三段内容。')
  await page.locator('.home-send').click()

  const editor = page.locator('.editor-scroll .ProseMirror')
  await expect(editor).toBeVisible({ timeout: 60_000 })
  // wait until real generated content has landed in the editor
  await page.waitForFunction(
    () => {
      const el = document.querySelector('.editor-scroll .ProseMirror')
      return !!el && el.textContent!.length > 100
    },
    undefined,
    { timeout: 300_000 },
  )
})

test('generate a PPT deck from the Home composer', async ({ page }) => {
  await registerViaUi(page)
  await page.locator('.home-kind-btn', { hasText: '演示文稿' }).click()
  await page.locator('.home-input').fill('帮我做一份3页的产品发布演示文稿。')
  await page.locator('.home-send').click()
  await page.waitForURL(/\/slides\//, { timeout: 15_000 })

  await expect(page.locator('.start-booting')).toHaveCount(0, { timeout: 300_000 })
  // a real multi-page deck, not a blank single slide. The model may first ask
  // clarifying questions — answer them, then wait for pages to render.
  await expect
    .poll(async () => {
      if ((await page.locator('.ai-clarify-card').count()) > 0) await answerClarify(page)
      return page.locator('.slide-list .thumb').count()
    }, { timeout: 300_000 })
    .toBeGreaterThanOrEqual(2)
})

test('generate a spreadsheet from the Home composer', async ({ page }) => {
  await registerViaUi(page)
  await page.locator('.home-kind-btn', { hasText: '表格' }).click()
  await page.locator('.home-input').fill('帮我做一张简单的家庭月度预算表。')
  await page.locator('.home-send').click()
  await page.waitForURL(/\/sheets\//, { timeout: 15_000 })

  await expect(page.locator('#univer-container.spreadsheet')).toBeVisible({ timeout: 120_000 })
  // The completed AI run auto-saves the workbook to the backend. Poll the
  // recent-docs API until the .xlsx count grows past the seed sample (1 → ≥2).
  await expect
    .poll(
      async () => {
        const titles = await page.evaluate(async () => {
          const r = await fetch('/documents', {
            headers: { Authorization: `Bearer ${localStorage.getItem('aioffice_token')}` },
          })
          if (!r.ok) return [] as string[]
          return (await r.json()).map((d: { title?: string }) => String(d.title ?? ''))
        })
        return titles.filter((t) => t.endsWith('.xlsx')).length
      },
      { timeout: 300_000 },
    )
    .toBeGreaterThanOrEqual(2)
})
