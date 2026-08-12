import { expect, test } from '@playwright/test'

// 技能中心 (Skill Center): a fresh account is seeded with the bundled 去AI味
// (humanizer) skill, and it must show up in the SkillManager opened from Home.

const email = () => `e2e-skill-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`
const PW = 'e2e-password-123'

test('new user sees the seeded humanizer skill in 技能中心', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.login-screen')).toBeVisible()
  await page.locator('.login-switch').click() // login → register
  await page.locator('input[type="email"]').fill(email())
  await page.locator('input[type="password"]').fill(PW)
  await page.locator('.login-submit').click()
  await expect(page.locator('.home')).toBeVisible()

  // open the Skill Center from the sidebar nav
  await page.locator('.home-nav-item', { hasText: '技能中心' }).click()

  // SkillManager loads /skills and lists the seeded skill row
  await expect(page.getByText('humanizer')).toBeVisible({ timeout: 15000 })
  // it is enabled by default and carries a version badge
  await expect(page.getByText('v4.1.0')).toBeVisible()

  // open its detail → SKILL.md body renders
  await page.getByRole('button', { name: '查看' }).first().click()
  await expect(page.getByText('AI 味去除')).toBeVisible({ timeout: 10000 })
})
