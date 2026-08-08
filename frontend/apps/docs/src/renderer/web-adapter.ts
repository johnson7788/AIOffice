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

const desktop: DesktopApi = {
  getLanguage: async () => 'zh',
  onLanguageChanged: unsub,

  openDocx: async () => {
    const f = await pickFile('.docx')
    if (!f) return null
    const data = await f.arrayBuffer()
    return { path: f.name, name: f.name, data, hash: await sha256Hex(data) }
  },
  openDocxPath: async () => null,
  consumePendingOpenDocx: async () => null,
  consumeNewBlankDoc: async () => true, // M0: always start blank
  onOpenDocx: unsub,
  onRenamedDocx: unsub,
  saveDocx: async (path, data) => {
    downloadBytes(path || 'document.docx', data)
    return { ok: true }
  },
  writeRecoveryCopy: async () => ({ ok: true }),
  onTeardown: unsub,
  saveDocxAs: async (defaultName, data) => {
    downloadBytes(defaultName, data)
    return { ok: true, path: defaultName }
  },
  saveDocxNew: async (defaultName, data) => {
    downloadBytes(defaultName, data)
    return { ok: true, path: defaultName }
  },
  getRecentFiles: async () => [],
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

// ── project/chat persistence (M0: in-memory) ──
const DEFAULT = { projectId: 'default', chatId: 'default' }
const projectApi: ProjectApi = {
  resolveChat: async (args) => ({
    projectId: DEFAULT.projectId,
    chatId: args.tempChatId ?? DEFAULT.chatId,
  }),
  appendChat: async () => {},
  loadChat: async () => [],
  rebindChat: async () => DEFAULT,
  listProjects: async () => [],
  createProject: async (args) =>
    ({ id: crypto.randomUUID(), name: args.name }) as unknown as Awaited<
      ReturnType<ProjectApi['createProject']>
    >,
  renameProject: async () => {},
  deleteProject: async () => {},
  moveFile: async () => {},
  getTimeline: async () => [],
}

declare global {
  interface Window {
    desktop: DesktopApi
    projectApi: ProjectApi
  }
}

window.desktop = desktop
window.projectApi = projectApi
