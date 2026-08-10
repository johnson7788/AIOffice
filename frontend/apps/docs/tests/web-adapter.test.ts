import { beforeEach, describe, expect, it, vi } from 'vitest'
import '../src/renderer/web-adapter' // installs window.desktop

const enc = new TextEncoder()

function sseBody(parts: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(c) {
      for (const p of parts) c.enqueue(enc.encode(p))
      c.close()
    },
  })
}

// aiStream kicks off async stream reading; resolve once a terminal chunk lands
function collectUntilDone(): Promise<Array<Record<string, unknown>>> {
  return new Promise((resolve) => {
    const got: Array<Record<string, unknown>> = []
    const off = window.desktop.onAiStream((chunk) => {
      const c = chunk as Record<string, unknown>
      got.push(c)
      if (c.type === 'done' || c.type === 'error') {
        off()
        resolve(got)
      }
    })
  })
}

describe('web-adapter aiStream SSE parsing', () => {
  it('parses data frames, including one split across stream chunks', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        body: sseBody([
          'data: {"requestId":"r1","type":"delta","text":"He"}\n\n',
          'data: {"requestId":"r1","typ', // frame deliberately split mid-JSON
          'e":"delta","text":"llo"}\n\n',
          'data: {"requestId":"r1","type":"done","stopReason":"stop"}\n\n',
        ]),
      })),
    )
    const done = collectUntilDone()
    await window.desktop.aiStream({ requestId: 'r1' } as Parameters<typeof window.desktop.aiStream>[0])
    expect(await done).toEqual([
      { requestId: 'r1', type: 'delta', text: 'He' },
      { requestId: 'r1', type: 'delta', text: 'llo' },
      { requestId: 'r1', type: 'done', stopReason: 'stop' },
    ])
  })

  it('emits an error chunk on a non-ok response', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, body: null })))
    const done = collectUntilDone()
    await window.desktop.aiStream({ requestId: 'r2' } as Parameters<typeof window.desktop.aiStream>[0])
    expect(await done).toEqual([{ requestId: 'r2', type: 'error', error: 'HTTP 500' }])
  })
})

interface Call {
  url: string
  method: string
  auth: string | null
}

// mock backend: the token is pre-seeded (post-login); serves document routes
function mockBackend(): Call[] {
  const calls: Call[] = []
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    const auth = init.headers ? new Headers(init.headers).get('Authorization') : null
    calls.push({ url, method, auth })
    const ok = (json: unknown, status = 200) => ({ ok: true, status, json: async () => json })
    if (url.includes('/documents?title=')) return ok({ id: 'doc1' }, 201)
    if (url.endsWith('/documents/doc1/blob') && method === 'PUT') return ok({ id: 'v2', size: 3 })
    if (url.endsWith('/documents/doc1/blob'))
      return {
        ok: true,
        status: 200,
        arrayBuffer: async () => enc.encode('DOCBYTES').buffer,
        headers: new Headers({ 'Content-Disposition': 'attachment; filename="report.docx"' }),
      }
    if (url.endsWith('/documents')) return ok([{ id: 'doc1' }, { id: 'doc2' }])
    return { ok: false, status: 404, json: async () => ({}) }
  })
  vi.stubGlobal('fetch', fn as unknown as typeof fetch)
  return calls
}

describe('web-adapter document storage', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('aioffice_token', 'TOK') // post-login
  })

  it('saveDocxNew creates a server document and returns its id as path', async () => {
    const calls = mockBackend()
    const res = await window.desktop.saveDocxNew('report.docx', enc.encode('body').buffer)
    expect(res).toEqual({ ok: true, path: 'doc1' })
    const post = calls.find((c) => c.url.includes('/documents?title='))!
    expect(post.method).toBe('POST')
    expect(post.auth).toBe('Bearer TOK') // seeded token attached
  })

  it('saveDocx uploads a new version via PUT', async () => {
    const calls = mockBackend()
    const res = await window.desktop.saveDocx('doc1', enc.encode('v2').buffer)
    expect(res).toEqual({ ok: true })
    const put = calls.find((c) => c.method === 'PUT')!
    expect(put.url).toBe('/documents/doc1/blob')
    expect(put.auth).toBe('Bearer TOK')
  })

  it('openDocxPath downloads bytes, filename, and hash', async () => {
    mockBackend()
    const r = await window.desktop.openDocxPath('doc1')
    expect(r).not.toBeNull()
    expect(r!.path).toBe('doc1')
    expect(r!.name).toBe('report.docx')
    expect(new TextDecoder().decode(r!.data)).toBe('DOCBYTES')
    expect(r!.hash).toMatch(/^[0-9a-f]{64}$/)
  })

  it('getRecentFiles returns document ids', async () => {
    mockBackend()
    expect(await window.desktop.getRecentFiles()).toEqual(['doc1', 'doc2'])
  })
})

// mock backend for the projectApi routes
function mockProjects(): Call[] {
  const calls: Call[] = []
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    const auth = init.headers ? new Headers(init.headers).get('Authorization') : null
    calls.push({ url, method, auth })
    const ok = (json: unknown) => ({ ok: true, status: 200, json: async () => json })
    if (url.endsWith('/projects/resolve-chat')) return ok({ projectId: 'p1', chatId: 'c1' })
    if (url.endsWith('/projects/append-chat')) return ok({ ok: true })
    if (url.includes('/projects/chat?')) return ok([{ seq: 1, ts: 't', role: 'user', text: 'hi' }])
    return ok([])
  })
  vi.stubGlobal('fetch', fn as unknown as typeof fetch)
  return calls
}

describe('web-adapter projectApi', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('aioffice_token', 'TOK')
  })

  it('resolveChat POSTs and returns the projectId/chatId', async () => {
    const calls = mockProjects()
    const ref = await window.projectApi.resolveChat({ filePath: null, tempChatId: 'u1' })
    expect(ref).toEqual({ projectId: 'p1', chatId: 'c1' })
    const post = calls.find((c) => c.url.endsWith('/projects/resolve-chat'))!
    expect(post.method).toBe('POST')
    expect(post.auth).toBe('Bearer TOK')
  })

  it('loadChat GETs by chatId', async () => {
    const calls = mockProjects()
    const msgs = await window.projectApi.loadChat({ projectId: 'p1', chatId: 'c1', limit: 50 })
    expect(msgs).toEqual([{ seq: 1, ts: 't', role: 'user', text: 'hi' }])
    expect(calls.some((c) => c.url.includes('/projects/chat?chatId=c1'))).toBe(true)
  })
})
