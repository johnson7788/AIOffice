/**
 * Web adapter: reimplements the Electron preload globals `window.desktop`
 * (DesktopApi) and `window.projectApi` (ProjectApi) for the browser SaaS.
 * Imported first in main.tsx so the globals exist before <App> mounts.
 *
 * M0 scope: boot a blank docx in the browser. AI + search go to the Python
 * backend; file open/save use browser file I/O; chat/project persistence is
 * in-memory. Real backend persistence lands in M1.
 * ponytail: docs-local for now; promote to a shared web-adapter package when
 * sheets/slides come online.
 */
import type { DesktopApi } from '../shared/ipc'
import type { ProjectApi } from '@genoffice/project-store'

// Empty = same origin; the Vite dev server proxies /ai /documents /files to the
// backend, so the index.html CSP (connect-src 'self') is satisfied.
const API = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

const noop = () => {}
const unsub = () => noop

async function sha256Hex(buf: ArrayBuffer): Promise<string> {
  const d = await crypto.subtle.digest('SHA-256', buf)
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

function pickFile(accept: string): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = accept
    input.onchange = () => resolve(input.files?.[0] ?? null)
    // if the dialog is dismissed there is no reliable event; leave it pending
    input.click()
  })
}

function downloadBytes(name: string, data: ArrayBuffer): void {
  const url = URL.createObjectURL(new Blob([data]))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// ── AI streaming over SSE (chunk shape = IpcStreamChunk / AiStreamChunk) ──
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
          if (!dataLine) continue
          emit(JSON.parse(dataLine.slice(5).trim()))
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

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (await r.json()) as T
}

// ── auth ──────────────────────────────────────────────────────────────────
// The Shell gates the app behind Login (see shell/), so a token is present
// before any authed call runs. On a 401 the token is cleared and the page
// reloads back to the login screen. Refresh tokens: M5.
export const TOKEN_KEY = 'aioffice_token'

export function hasToken(): boolean {
  return !!localStorage.getItem(TOKEN_KEY)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

/** Login or register; stores the token on success, else returns a message. */
export async function authenticate(
  email: string,
  password: string,
  mode: 'login' | 'register',
): Promise<{ ok: boolean; error?: string }> {
  let r: Response
  try {
    r = await fetch(`${API}/auth/${mode}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) }
  }
  if (!r.ok) {
    const msg =
      r.status === 401 ? '邮箱或密码错误' : r.status === 409 ? '该邮箱已注册' : `HTTP ${r.status}`
    return { ok: false, error: msg }
  }
  const { token } = (await r.json()) as { token: string }
  localStorage.setItem(TOKEN_KEY, token)
  return { ok: true }
}

function getToken(): string {
  const cached = localStorage.getItem(TOKEN_KEY)
  if (!cached) throw new Error('not authenticated')
  return cached
}

// Cross-app navigation. Prod: nginx serves docs at / and slides/pdf/markdown
// under /<app>/ (same origin, so localStorage token carries over). Dev: each app
// is its own vite server on a fixed port (separate origin), so the caller also
// appends ?tok= to hand the token across — the target adapter adopts it.
// ponytail: dev ports hardcoded to match vite.renderer.config.ts.
const DEV_PORTS: Record<string, string> = {
  docs: '3585',
  slides: '3586',
  pdf: '3587',
  markdown: '3588',
  sheets: '3589',
}
export function appUrl(app: 'docs' | 'slides' | 'pdf' | 'markdown' | 'sheets'): string {
  if (location.port === DEV_PORTS.docs) {
    const base = `${location.protocol}//${location.hostname}:${DEV_PORTS[app]}/`
    return `${base}?tok=${encodeURIComponent(localStorage.getItem(TOKEN_KEY) ?? '')}`
  }
  return app === 'docs' ? `${location.origin}/` : `${location.origin}/${app}/`
}

// authorized fetch; a 401 means the session died → bounce back to login
async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${getToken()}`)
  const r = await fetch(`${API}${path}`, { ...init, headers })
  if (r.status === 401) {
    clearToken()
    location.reload()
  }
  return r
}

function filenameFromDisposition(cd: string | null, fallback: string): string {
  const star = cd?.match(/filename\*=(?:UTF-8'')?([^;]+)/i)
  if (star) { try { return decodeURIComponent(star[1].replace(/"/g, '')) } catch { /* fall through */ } }
  const m = cd?.match(/filename="?([^";]+)"?/i)
  return m ? m[1] : fallback
}

async function createDocument(
  title: string,
  data: ArrayBuffer,
): Promise<{ ok: boolean; path?: string; error?: string }> {
  const r = await authFetch(`/documents?title=${encodeURIComponent(title)}`, {
    method: 'POST',
    body: data,
  })
  if (!r.ok) return { ok: false, error: `HTTP ${r.status}` }
  const { id } = (await r.json()) as { id: string }
  return { ok: true, path: id }
}

export interface DocMeta {
  id: string
  title: string
  type: string
  updated: string
}
/** recent documents with titles, for the Home sidebar */
export async function listDocuments(): Promise<DocMeta[]> {
  const r = await authFetch('/documents')
  return r.ok ? ((await r.json()) as DocMeta[]) : []
}

const desktop: DesktopApi = {
  getLanguage: async () => 'zh',
  onLanguageChanged: unsub,

  openDocx: async () => {
    const f = await pickFile('.docx')
    if (!f) return null
    const data = await f.arrayBuffer()
    return { path: f.name, name: f.name, data, hash: await sha256Hex(data) }
  },
  // `path` is the server document id
  openDocxPath: async (id) => {
    const r = await authFetch(`/documents/${id}/blob`)
    if (!r.ok) return null
    const data = await r.arrayBuffer()
    const name = filenameFromDisposition(r.headers.get('Content-Disposition'), id)
    return { path: id, name, data, hash: await sha256Hex(data) }
  },
  // Home stashes the doc id here before switching to the editor view
  consumePendingOpenDocx: async () => {
    const id = sessionStorage.getItem('aioffice.pendingOpen')
    if (!id) return null
    sessionStorage.removeItem('aioffice.pendingOpen')
    return desktop.openDocxPath(id)
  },
  consumeNewBlankDoc: async () => true, // M0: always start blank
  onOpenDocx: unsub,
  onRenamedDocx: unsub,
  // save an existing server document: uploads a new version
  saveDocx: async (path, data) => {
    const r = await authFetch(`/documents/${path}/blob`, { method: 'PUT', body: data })
    return r.ok ? { ok: true } : { ok: false, error: `HTTP ${r.status}` }
  },
  writeRecoveryCopy: async () => ({ ok: true }),
  onTeardown: unsub,
  saveDocxAs: async (defaultName, data) => createDocument(defaultName, data),
  // first save of a new document: creates it server-side, returns the new id as path
  saveDocxNew: async (defaultName, data) => createDocument(defaultName, data),
  getRecentFiles: async () =>
    authFetch('/documents')
      .then((r) => (r.ok ? r.json() : []))
      .then((docs: Array<{ id: string }>) => docs.map((d) => d.id))
      .catch(() => []),
  pickImage: async () => {
    const f = await pickFile('image/*')
    if (!f) return null
    const buf = new Uint8Array(await f.arrayBuffer())
    let bin = ''
    for (const b of buf) bin += String.fromCharCode(b)
    const mime = f.type === 'image/jpeg' || f.type === 'image/gif' ? f.type : 'image/png'
    return { base64: btoa(bin), mime, name: f.name }
  },
  getAiSettings: async () => ({ provider: 'backend' }) as unknown as Awaited<
    ReturnType<DesktopApi['getAiSettings']>
  >,
  setAiSettings: async () => {},
  print: async () => window.print(),
  exportPdf: async () => ({ ok: false, error: 'not supported in web M0' }),
  printPdfBuffer: async () => ({ ok: false, error: 'not supported in web M0' }),
  saveMergedPdf: async () => ({ ok: false, error: 'not supported in web M0' }),

  aiChat: async () => ({ text: '' }) as unknown as Awaited<ReturnType<DesktopApi['aiChat']>>,
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
  aiGskStatus: async () =>
    ({ loggedIn: true }) as unknown as Awaited<ReturnType<DesktopApi['aiGskStatus']>>,
  aiGskLogin: async () => {},
  webSearch: async (query, maxResults) =>
    getJson(`/ai/web-search?query=${encodeURIComponent(query)}&max=${maxResults ?? 6}`).catch(
      () => ({ results: [], method: 'error', error: 'search unavailable' }),
    ) as ReturnType<DesktopApi['webSearch']>,
  imageSearch: async (query, maxResults) =>
    getJson(`/ai/image-search?query=${encodeURIComponent(query)}&max=${maxResults ?? 8}`).catch(
      () => ({ images: [], method: 'error', error: 'search unavailable' }),
    ) as ReturnType<DesktopApi['imageSearch']>,
  fetchImage: async (url) =>
    getJson<{ base64: string; mime: string }>(
      `/ai/fetch-image?url=${encodeURIComponent(url)}`,
    ).catch(() => null),

  pickAttachments: async () => null,
  addAttachmentPaths: async () => ({ accepted: [], rejected: [] }),
  addPastedImage: async () => ({ accepted: [], rejected: [] }),
  readAttachment: async () => ({ ok: false, error: 'not supported in web M0' }),
  readAttachmentImage: async () => ({ ok: false, error: 'not supported in web M0' }),
  getPathForFile: (file) => file.name,

  openNewTab: async () => {},
  listDocsTabs: async () => [],
  focusDocsTab: async () => {},

  onAiStream: (handler) => {
    streamListeners.add(handler as StreamListener)
    return () => streamListeners.delete(handler as StreamListener)
  },
  onMenuCommand: unsub,
  onCloseCheck: unsub,
  reportCloseCheck: noop,
  onCloseSaveRequest: unsub,
  reportCloseSaveResult: noop,
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
async function apiJson<T>(path: string, init: RequestInit): Promise<T> {
  const r = await authFetch(path, init)
  return (await r.json()) as T
}

const projectApi: ProjectApi = {
  resolveChat: (args) =>
    apiPost('/projects/resolve-chat', { filePath: args.filePath, tempChatId: args.tempChatId }),
  appendChat: async (args) => {
    await apiPost('/projects/append-chat', args)
  },
  loadChat: (args) =>
    apiJson(
      `/projects/chat?chatId=${encodeURIComponent(args.chatId)}&limit=${args.limit ?? 200}`,
      {},
    ),
  rebindChat: (args) => apiPost('/projects/rebind-chat', args),
  listProjects: () => apiJson('/projects', {}),
  createProject: (args) => apiPost('/projects', args),
  renameProject: async (args) => {
    await authFetch(`/projects/${args.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: args.name }),
    })
  },
  deleteProject: async (args) => {
    await authFetch(`/projects/${args.id}`, { method: 'DELETE' })
  },
  moveFile: async (args) => {
    await apiPost('/projects/move-file', args)
  },
  getTimeline: (args) =>
    apiJson(`/projects/${args.projectId}/timeline?limit=${args.limit ?? 50}`, {}),
}

declare global {
  interface Window {
    desktop: DesktopApi
    projectApi: ProjectApi
  }
}

window.desktop = desktop
window.projectApi = projectApi

// ── Home document actions: versions + download ────────────────────────────
export interface VersionMeta {
  id: string
  size: number
  created: string
}
export async function listVersions(docId: string): Promise<VersionMeta[]> {
  const r = await authFetch(`/documents/${docId}/versions`)
  return r.ok ? ((await r.json()) as VersionMeta[]) : []
}
/** restore an older version: backend copies its bytes forward as the new latest */
export async function restoreVersion(docId: string, verId: string): Promise<boolean> {
  const r = await authFetch(`/documents/${docId}/versions/${verId}/restore`, { method: 'POST' })
  return r.ok
}
/** download a document's latest blob under its title */
export async function downloadDocument(docId: string, title: string): Promise<void> {
  const r = await authFetch(`/documents/${docId}/blob`)
  if (!r.ok) return
  const url = URL.createObjectURL(await r.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = title
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// ── Share links (public read-only; backend M5 /documents/{id}/share*) ─────
export interface ShareMeta {
  token: string
  docId: string
  created: string
}
export async function createShare(docId: string): Promise<ShareMeta | null> {
  const r = await authFetch(`/documents/${docId}/share`, { method: 'POST' })
  if (!r.ok) return null
  const s = (await r.json()) as { token: string; doc_id: string; created: string }
  return { token: s.token, docId: s.doc_id, created: s.created }
}
export async function listShares(docId: string): Promise<ShareMeta[]> {
  const r = await authFetch(`/documents/${docId}/shares`)
  if (!r.ok) return []
  const rows = (await r.json()) as { token: string; doc_id: string; created: string }[]
  return rows.map((s) => ({ token: s.token, docId: s.doc_id, created: s.created }))
}
export async function revokeShare(docId: string, token: string): Promise<boolean> {
  const r = await authFetch(`/documents/${docId}/share/${token}`, { method: 'DELETE' })
  return r.ok
}
/** public read-only landing URL for a share token (opens the docs SPA's ShareView) */
export function shareUrl(token: string): string {
  return `${location.origin}${location.pathname}?share=${encodeURIComponent(token)}`
}
/** public (no-auth) share metadata for the landing page */
export async function fetchSharedMeta(
  token: string,
): Promise<{ title: string; type: string } | null> {
  const r = await fetch(`${API}/share/${token}`).catch(() => null)
  if (!r?.ok) return null
  const m = (await r.json()) as { title: string; type: string }
  return { title: m.title, type: m.type }
}
/** public (no-auth) download of a shared document's blob */
export async function downloadShared(token: string, title: string): Promise<void> {
  const r = await fetch(`${API}/share/${token}/blob`).catch(() => null)
  if (!r?.ok) return
  const url = URL.createObjectURL(await r.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = title
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// ── Home sidebar: projects + which docs belong to each ────────────────────
export interface ProjectMeta {
  id: string
  name: string
  isDefault: boolean
}
export async function listProjects(): Promise<ProjectMeta[]> {
  const ps = await projectApi.listProjects()
  return ps.map((p) => ({ id: p.id, name: p.name, isDefault: p.isDefault }))
}
/** doc ids in a project, derived from its chat timeline (chat_key == doc id).
 *  ponytail: N+1 (one timeline call per project); fine for a personal SaaS. */
export async function projectDocIds(projectId: string): Promise<string[]> {
  const entries = await projectApi.getTimeline({ projectId, limit: 500 })
  return [...new Set(entries.map((e) => e.filePath))]
}
