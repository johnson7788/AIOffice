import { expect, test } from '@playwright/test'

// Full UI journey through the docs SPA shell: Login → Home → editor → back.
// Each run registers a fresh account so it is independent and repeatable.

const email = () => `e2e-ui-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`
const PW = 'e2e-password-123'

async function registerViaUi(page: import('@playwright/test').Page) {
  await page.goto('/')
  await expect(page.locator('.login-screen')).toBeVisible()
  await page.locator('.login-switch').click() // login → register
  await page.locator('input[type="email"]').fill(email())
  await page.locator('input[type="password"]').fill(PW)
  await page.locator('.login-submit').click()
  await expect(page.locator('.home')).toBeVisible()
}

test('register lands on Home', async ({ page }) => {
  await registerViaUi(page)
  await expect(page.locator('.home-heading')).toBeVisible()
  // file-type selector (文字文档 / 演示文稿) + at least the "new" buttons
  await expect(page.locator('.home-kind-btn.active')).toBeVisible()
  await expect(page.locator('.home-new').first()).toBeVisible()
})

test('auth persists across a reload', async ({ page }) => {
  await registerViaUi(page)
  await page.reload()
  // still authed → Home, not the login gate
  await expect(page.locator('.home')).toBeVisible()
  await expect(page.locator('.login-screen')).toHaveCount(0)
})

test('logout returns to the login gate', async ({ page }) => {
  await registerViaUi(page)
  await page.locator('.home-logout').click()
  await expect(page.locator('.login-screen')).toBeVisible()
})

test('new document opens the editor, back returns Home', async ({ page }) => {
  await registerViaUi(page)
  await page.locator('.home-new').first().click() // 文字文档 → docs editor
  // the docs App mounts full-screen with the shell back button + a ProseMirror surface
  await expect(page.locator('.shell-home-btn')).toBeVisible()
  const editor = page.locator('.editor-scroll .ProseMirror')
  await expect(editor).toBeVisible({ timeout: 15000 })
  await editor.click()
  await page.keyboard.type('Hello from Playwright')
  await expect(editor).toContainText('Hello from Playwright')

  await page.locator('.shell-home-btn').click()
  await expect(page.locator('.home')).toBeVisible()
})
