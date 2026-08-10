import { expect, test } from '@playwright/test'
import { loginViaUi, registerViaUi } from './helpers'

// Full-file journey: register → logout → login, then open each seeded document
// type (Word / PPT / Excel) in its own editor. The three seeds are created by
// backend/app/seed.py on register, so a fresh account always has them in Home.
// Deterministic — no AI calls.

const OPEN_TIMEOUT = 90_000

test('register, logout, login, then open the seeded Word doc in the docs editor', async ({
  page,
}) => {
  const mail = await registerViaUi(page)

  // logout → login gate → login with the same account
  await page.locator('.home-logout').click()
  await expect(page.locator('.login-screen')).toBeVisible()
  await loginViaUi(page, mail)
  await expect(page.locator('.home')).toBeVisible()

  // the .docx seed opens in-app (sessionStorage handoff) — no navigation
  await page.locator('.home-recent-item', { hasText: 'Word 示例' }).click()
  const editor = page.locator('.editor-scroll .ProseMirror')
  await expect(editor).toBeVisible({ timeout: OPEN_TIMEOUT })
  // real seeded content parsed by docx-engine, not a blank doc
  await expect(editor).toContainText('三步快速开始')
  await expect(page.locator('.shell-home-btn')).toBeVisible()
})

test('open the seeded PPT in the slides editor', async ({ page }) => {
  await registerViaUi(page)
  await page.locator('.home-recent-item', { hasText: 'PPT' }).click()
  await page.waitForURL(/\/slides\//, { timeout: 15_000 })

  // deck loaded: booting screen gone, thumbnail sidebar rendered
  await expect(page.locator('.start-booting')).toHaveCount(0, { timeout: OPEN_TIMEOUT })
  await expect(page.locator('.workspace .slide-list .thumb').first()).toBeVisible({
    timeout: OPEN_TIMEOUT,
  })
  // the seed has 2 slides (欢迎使用 AI Office 演示 / 三步快速上手)
  await expect.poll(() => page.locator('.slide-list .thumb').count()).toBeGreaterThanOrEqual(2)
})

test('open the seeded Excel in the sheets editor', async ({ page }) => {
  await registerViaUi(page)
  await page.locator('.home-recent-item', { hasText: '表格示例' }).click()
  await page.waitForURL(/\/sheets\//, { timeout: 15_000 })

  // Univer mounts its surface once the xlsx (sidecar-parsed) workbook is open
  await expect(page.locator('#univer-container.spreadsheet')).toBeVisible({
    timeout: OPEN_TIMEOUT,
  })
})
