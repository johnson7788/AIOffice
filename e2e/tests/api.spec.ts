import { expect, test } from '@playwright/test'

// Backend e2e through the nginx reverse proxy (same origin the SPAs use).
// Deterministic — no AI/model calls, so these are fast and never flake on tokens.

const rnd = () => Math.random().toString(36).slice(2, 10)
const newEmail = () => `e2e-${Date.now()}-${rnd()}@example.com`
const PW = 'e2e-password-123'

async function register(request: import('@playwright/test').APIRequestContext) {
  const r = await request.post('/auth/register', {
    data: { email: newEmail(), password: PW },
  })
  expect(r.ok(), `register failed: ${r.status()}`).toBeTruthy()
  const body = (await r.json()) as { token: string; user_id: string; org_id: string }
  expect(body.token).toBeTruthy()
  return body.token
}

const auth = (token: string) => ({ Authorization: `Bearer ${token}` })

test('healthz is up', async ({ request }) => {
  const r = await request.get('/healthz')
  expect(r.ok()).toBeTruthy()
})

test('register issues a JWT and /auth/me echoes the user', async ({ request }) => {
  const token = await register(request)
  const me = await request.get('/auth/me', { headers: auth(token) })
  expect(me.ok()).toBeTruthy()
  const body = (await me.json()) as { id: string; email: string }
  expect(body.email).toContain('@example.com')
})

test('login fails with a wrong password', async ({ request }) => {
  const email = newEmail()
  const reg = await request.post('/auth/register', { data: { email, password: PW } })
  expect(reg.ok()).toBeTruthy()
  const bad = await request.post('/auth/login', { data: { email, password: 'wrong-password' } })
  expect(bad.status()).toBe(401)
})

test('document roundtrip: create → read blob → list', async ({ request }) => {
  const token = await register(request)
  const content = `hello e2e ${rnd()}`

  const created = await request.post('/documents?title=E2E%20Doc.md', {
    headers: auth(token),
    data: content,
  })
  expect(created.ok()).toBeTruthy()
  const { id } = (await created.json()) as { id: string }
  expect(id).toBeTruthy()

  const blob = await request.get(`/documents/${id}/blob`, { headers: auth(token) })
  expect(blob.ok()).toBeTruthy()
  expect(await blob.text()).toBe(content)

  const list = await request.get('/documents', { headers: auth(token) })
  expect(list.ok()).toBeTruthy()
  const docs = (await list.json()) as Array<{ id: string; title: string }>
  expect(docs.some((d) => d.id === id)).toBeTruthy()
})

test('a new version bumps the blob content', async ({ request }) => {
  const token = await register(request)
  const created = await request.post('/documents?title=v.md', { headers: auth(token), data: 'v1' })
  const { id } = (await created.json()) as { id: string }

  const put = await request.put(`/documents/${id}/blob`, { headers: auth(token), data: 'v2' })
  expect(put.ok()).toBeTruthy()
  const blob = await request.get(`/documents/${id}/blob`, { headers: auth(token) })
  expect(await blob.text()).toBe('v2')
})

test('tenant isolation: another org cannot read the doc (404)', async ({ request }) => {
  const owner = await register(request)
  const created = await request.post('/documents?title=secret.md', {
    headers: auth(owner),
    data: 'top secret',
  })
  const { id } = (await created.json()) as { id: string }

  const intruder = await register(request) // a fresh register = its own org
  const stolen = await request.get(`/documents/${id}/blob`, { headers: auth(intruder) })
  expect(stolen.status()).toBe(404)
})

test('unauthenticated document access is rejected (401)', async ({ request }) => {
  const r = await request.get('/documents')
  expect(r.status()).toBe(401)
})

for (const app of ['/', '/slides/', '/pdf/', '/markdown/', '/sheets/']) {
  test(`static SPA served at ${app}`, async ({ request }) => {
    const r = await request.get(app)
    expect(r.ok(), `${app} → ${r.status()}`).toBeTruthy()
    expect(await r.text()).toContain('<div id="root">')
  })
}
