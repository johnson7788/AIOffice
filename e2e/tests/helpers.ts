import { expect, type Page } from '@playwright/test'

// Shared UI helpers for the docs SPA shell (Login → Home). Each test registers a
// fresh account so runs are independent and repeatable.

export const PW = 'e2e-password-123'
export const email = () =>
  `e2e-apps-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`

export async function registerViaUi(page: Page, mail?: string): Promise<string> {
  const addr = mail ?? email()
  await page.goto('/')
  await expect(page.locator('.login-screen')).toBeVisible()
  await page.locator('.login-switch').click() // login → register
  await page.locator('input[type="email"]').fill(addr)
  await page.locator('input[type="password"]').fill(PW)
  await page.locator('.login-submit').click()
  await expect(page.locator('.home')).toBeVisible()
  return addr
}

export async function loginViaUi(page: Page, mail: string): Promise<void> {
  await page.goto('/')
  await expect(page.locator('.login-screen')).toBeVisible()
  await page.locator('input[type="email"]').fill(mail)
  await page.locator('input[type="password"]').fill(PW)
  await page.locator('.login-submit').click()
  await expect(page.locator('.home')).toBeVisible()
}
