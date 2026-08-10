import { chromium } from '@playwright/test'

// One-off diagnostic: register via API, then open the seeded PDF in the pdf app
// and capture console / page errors + a screenshot to see WHY it fails.
const BASE = 'http://localhost:8080'

async function main() {
  const mail = `diag-${Date.now()}@example.com`
  const r = await fetch(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: mail, password: 'e2e-password-123' }),
  })
  const { token } = await r.json()
  const docsR = await fetch(`${BASE}/documents`, { headers: { Authorization: `Bearer ${token}` } })
  const docs = await docsR.json()
  const pdf = docs.find((d: { title: string }) => d.title.endsWith('.pdf'))
  console.log('DOC', JSON.stringify(pdf))

  const browser = await chromium.launch()
  const page = await browser.newPage()
  const logs: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error' || m.type() === 'warning') logs.push(`[console.${m.type()}] ${m.text().slice(0, 260)}`)
  })
  page.on('pageerror', (e) => logs.push(`[pageerror] ${String(e).slice(0, 260)}`))
  page.on('response', (res) => {
    if (res.status() >= 400) logs.push(`[HTTP ${res.status()}] ${res.url()}`)
  })

  // seed the token on the pdf origin first
  await page.goto(`${BASE}/pdf/`)
  await page.evaluate((t) => localStorage.setItem('aioffice_token', t), token)
  await page.goto(`${BASE}/pdf/?doc=${pdf.id}`)
  await page.waitForTimeout(8000)
  await page.screenshot({ path: '/tmp/pdf-diag.png' })

  console.log('URL:', page.url())
  console.log('thumb-boxes:', await page.locator('.pdf-thumb-box').count())
  console.log('pdf-page-count:', await page.locator('.pdf-page').count())
  console.log('textLayer count:', await page.locator('.pdf-page-content .textLayer').count())
  console.log('p1 text:', JSON.stringify((await page.locator('.pdf-page-content .textLayer').first().textContent()).slice(0, 80)))
  console.log('--- LOGS ---')
  console.log(logs.slice(0, 60).join('\n') || '(none)')
  await browser.close()
}
main()
