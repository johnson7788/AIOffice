/**
 * Web adapter: reimplements the Electron preload globals `window.markdownApi`
 * (MarkdownApi) and `window.projectApi` for the browser SaaS. Imported first in
 * main.tsx so the globals exist before <App> mounts.
 *
 * Markdown docs are plain UTF-8 text blobs stored in the Python backend over
 * HTTP; AI streams over SSE. Images are inlined as `data:` URLs (no assets/ dir
 * on the web) — resolveImageSrc/serialization keep them verbatim. Auth token is
 * shared via localStorage with the docs Shell (same origin); this app has no
 * login of its own — open it after logging in through docs.
 * ponytail: data: URL images, no shell menu (App's own Cmd+S drives save).
 */
import type { ProjectApi } from '@genoffice/project-store'
import type {
  ExportDocxRequest,
  ExportPdfRequest,
  ExportResult,
  ImageData,
  MarkdownApi,
  SaveMarkdownRequest,
  SaveMarkdownResult,
} from '../shared/ipc'

const API = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
const noop = () => {}
const unsub = () => noop
const TOKEN_KEY = 'aioffice_token'

// the server document id backing the open editor (null = untitled)
let currentId: string | null = null

// Dev cross-origin handoff: the docs Home appends ?tok= when navigating here
// (separate vite origins don't share localStorage). Adopt it, then strip only
// the tok param so ?doc=/?gen=/?view= survive for the App boot. No-op in prod
// (same origin → token already present, no ?tok appended).
;(() => {
  const p = new URLSearchParams(location.search)
  const tok = p.get('tok')
  if (!tok) return
  localStorage.setItem(TOKEN_KEY, tok)
  p.delete('tok')
  const q = p.toString()
  history.replaceState(null, '', location.pathname + (q ? `?${q}` : ''))
})()

function getToken(): string {
  const t = localStorage.getItem(TOKEN_KEY)
  if (!t) throw new Error('not authenticated')
  return t
}

async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${getToken()}`)
  const r = await fetch(`${API}${path}`, { ...init, headers })
  if (r.status === 401) {
    localStorage.removeItem(TOKEN_KEY)
    location.reload()
  }
  return r
}

function pickFile(accept: string): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = accept
    input.onchange = () => resolve(input.files?.[0] ?? null)
    input.click()
  })
}

function downloadBytes(name: string, data: Uint8Array): void {
  const url = URL.createObjectURL(new Blob([data as BlobPart]))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

async function fileToDataUrl(file: File): Promise<string> {
  const buf = new Uint8Array(await file.arrayBuffer())
  let bin = ''
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000))
  const mime = /jpe?g|gif|png/.test(file.type) ? file.type : 'image/png'
  return `data:${mime};base64,${btoa(bin)}`
}

async function createDocument(title: string, bytes: Uint8Array): Promise<string> {
  const r = await authFetch(`/documents?title=${encodeURIComponent(title)}`, {
    method: 'POST',
    body: bytes as BodyInit,
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return ((await r.json()) as { id: string }).id
}

// ── AI streaming over SSE (chunk shape = AiStreamChunk) ──
type StreamListener = (chunk: unknown) => void
const streamListeners = new Set<StreamListener>()
const controllers = new Map<string, AbortController>()
const emit = (chunk: unknown) => streamListeners.forEach((l) => l(chunk))

async function aiStream(request: { requestId: string }): Promise<void> {
  const { requestId } = request
  const ac = new AbortController()
  controllers.set(requestId, ac)
  let resp: Response
  try {
    resp = await fetch(`${API}/ai/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal: ac.signal,
    })
  } catch (e) {
    controllers.delete(requestId)
    emit({ requestId, type: 'error', error: e instanceof Error ? e.message : String(e) })
    return
  }
  if (!resp.ok || !resp.body) {
    controllers.delete(requestId)
    emit({ requestId, type: 'error', error: `HTTP ${resp.status}` })
    return
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  void (async () => {
    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        let idx: number
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const frame = buf.slice(0, idx)
          buf = buf.slice(idx + 2)
          const dataLine = frame.split('\n').find((l) => l.startsWith('data:'))
          if (dataLine) emit(JSON.parse(dataLine.slice(5).trim()))
        }
      }
    } catch (e) {
      if (!ac.signal.aborted)
        emit({ requestId, type: 'error', error: e instanceof Error ? e.message : String(e) })
    } finally {
      controllers.delete(requestId)
    }
  })()
}

const api: MarkdownApi = {
  // Home/docs stashes the doc id in the URL (?doc=) or sessionStorage before opening this app
  consumePending: async () => {
    const fromUrl = new URLSearchParams(location.search).get('doc')
    if (fromUrl) return fromUrl
    const id = sessionStorage.getItem('aioffice.pendingOpen')
    if (id) sessionStorage.removeItem('aioffice.pendingOpen')
    return id
  },

  // `path` is the server document id; text blob
  readFile: async (path) => {
    const r = await authFetch(`/documents/${path}/blob`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    currentId = path
    return await r.text()
  },

  save: async (request: SaveMarkdownRequest): Promise<SaveMarkdownResult> => {
    try {
      const bytes = new TextEncoder().encode(request.text)
      if (request.mode === 'saveAs' || !currentId) {
        currentId = await createDocument(request.suggestedName || 'Untitled', bytes)
      } else {
        const r = await authFetch(`/documents/${currentId}/blob`, {
          method: 'PUT',
          body: bytes as BodyInit,
        })
        if (!r.ok) return { ok: false, error: `HTTP ${r.status}` }
      }
      return { ok: true, path: currentId }
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) }
    }
  },

  setDirty: noop,
  onSaveRequest: unsub, // no shell menu on web; App wires its own Cmd/Ctrl+S
  sendSaveRequestAck: noop,
  onCloseSaveRequest: unsub,
  sendCloseSaveResult: noop,
  onFileRenamed: unsub,

  // web has no assets/ dir — inline images as data: URLs (resolveImageSrc keeps them verbatim)
  pickImage: async () => {
    const f = await pickFile('image/png,image/jpeg,image/gif')
    return f ? fileToDataUrl(f) : null
  },
  saveImage: async ({ base64, ext }) => {
    const mime = ext === 'jpg' || ext === 'jpeg' ? 'image/jpeg' : ext === 'gif' ? 'image/gif' : 'image/png'
    return `data:${mime};base64,${base64}`
  },
  readImage: async (src): Promise<ImageData | null> => {
    const m = src.match(/^data:(image\/(?:png|jpeg|gif));base64,(.*)$/)
    if (m) return { base64: m[2], mime: m[1] as ImageData['mime'] }
    if (/^https?:/i.test(src)) {
      const r = await fetch(`${API}/ai/fetch-image?url=${encodeURIComponent(src)}`).catch(() => null)
      if (!r?.ok) return null
      const { base64, mime } = (await r.json()) as { base64: string; mime: string }
      const mm = mime === 'image/jpeg' || mime === 'image/gif' ? mime : 'image/png'
      return { base64, mime: mm }
    }
    return null
  },

  onExportRequest: unsub, // no shell menu on web
  exportDocx: async (request: ExportDocxRequest): Promise<ExportResult> => {
    try {
      const bytes = b64ToBytes(request.base64)
      if (request.mode === 'openInDocs') {
        const id = await createDocument(request.suggestedName, bytes)
        return { ok: true, path: id }
      }
      downloadBytes(`${request.suggestedName}.docx`, bytes)
      return { ok: true, path: request.suggestedName }
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) }
    }
  },
  exportPdf: async (request: ExportPdfRequest): Promise<ExportResult> => {
    const w = window.open('', '_blank')
    if (!w) return { ok: false, error: 'popup blocked' }
    w.document.write(request.html)
    w.document.close()
    w.focus()
    w.print()
    return { ok: true, path: request.suggestedName }
  },

  getLanguage: async () => 'zh',
  onLanguageChanged: unsub,

  getAiSettings: async () =>
    ({ provider: 'backend' }) as unknown as Awaited<ReturnType<MarkdownApi['getAiSettings']>>,
  aiStream,
  aiStreamCancel: async (requestId) => {
    controllers.get(requestId)?.abort()
    controllers.delete(requestId)
    await fetch(`${API}/ai/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ requestId }),
    }).catch(noop)
  },
  onAiStream: (handler) => {
    streamListeners.add(handler as StreamListener)
    return () => streamListeners.delete(handler as StreamListener)
  },
  webSearch: async (query, maxResults) => {
    const r = await fetch(
      `${API}/ai/web-search?query=${encodeURIComponent(query)}&max=${maxResults ?? 6}`,
    ).catch(() => null)
    if (!r?.ok) return { results: [] }
    return (await r.json()) as Awaited<ReturnType<MarkdownApi['webSearch']>>
  },
}

/** Online image search for the shared ImageGallery (unauthenticated backend proxy). */
export async function imageSearch(
  query: string,
  maxResults = 24,
): Promise<{ images: Array<{ title: string; imageUrl: string; sourceUrl?: string; source?: string; width?: number; height?: number }> }> {
  const r = await fetch(
    `${API}/ai/image-search?query=${encodeURIComponent(query)}&max=${maxResults}`,
  ).catch(() => null)
  if (!r?.ok) return { images: [] }
  return (await r.json()) as { images: [] }
}

// ── project/chat persistence (backend: /projects) ──
async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await authFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await r.json()) as T
}

const projectApi: Pick<ProjectApi, 'resolveChat' | 'appendChat' | 'loadChat' | 'rebindChat'> = {
  resolveChat: (args) =>
    apiPost('/projects/resolve-chat', { filePath: args.filePath, tempChatId: args.tempChatId }),
  appendChat: async (args) => {
    await apiPost('/projects/append-chat', args)
  },
  loadChat: async (args) => {
    const r = await authFetch(
      `/projects/chat?chatId=${encodeURIComponent(args.chatId)}&limit=${args.limit ?? 200}`,
    )
    return (await r.json()) as Awaited<ReturnType<ProjectApi['loadChat']>>
  },
  rebindChat: (args) => apiPost('/projects/rebind-chat', args),
}

// window.markdownApi + window.projectApi types are declared in env.d.ts
window.markdownApi = api
window.projectApi = projectApi
