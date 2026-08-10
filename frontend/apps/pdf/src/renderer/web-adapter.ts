/**
 * Web adapter: reimplements the Electron preload global `window.pdfApi` (PdfApi)
 * for the browser SaaS. Imported first in main.tsx so the global exists before
 * <App> mounts.
 *
 * PDF mutation (markups/drawings/forms/page ops) runs client-side via pdf-lib
 * (adapter/pdf-edit.ts, ported from the Electron main process). File I/O goes to
 * the Python backend over HTTP; AI streams over SSE. Auth token is shared via
 * localStorage with the docs Shell (same origin) — this app has no login of its
 * own; open it after logging in through docs. ponytail: no separate pdf login.
 */
import type {
  ExportImagesRequest,
  ExportImagesResult,
  ExtractPagesRequest,
  ExtractPagesResult,
  InsertPdfRequest,
  InsertPdfResult,
  PdfApi,
  SavePdfRequest,
  SavePdfResult,
} from '../shared/ipc'
import { applySaveRequest, extractPagesBytes, insertPdfBytes } from './adapter/pdf-edit'

const API = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
const noop = () => {}
const unsub = () => noop
const TOKEN_KEY = 'aioffice_token'

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

async function readBytes(id: string): Promise<Uint8Array> {
  const r = await authFetch(`/documents/${id}/blob`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return new Uint8Array(await r.arrayBuffer())
}

async function putBytes(id: string, bytes: Uint8Array): Promise<Response> {
  return authFetch(`/documents/${id}/blob`, { method: 'PUT', body: bytes as BodyInit })
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

const api: PdfApi = {
  // Home/docs stashes the doc id in the URL (?doc=) or sessionStorage before opening this app
  consumePending: async () => {
    const fromUrl = new URLSearchParams(location.search).get('doc')
    if (fromUrl) return fromUrl
    const id = sessionStorage.getItem('aioffice.pendingOpen')
    if (id) sessionStorage.removeItem('aioffice.pendingOpen')
    return id
  },
  // `path` is the server document id
  readFile: async (path) => (await readBytes(path)).buffer as ArrayBuffer,

  save: async (request: SavePdfRequest): Promise<SavePdfResult> => {
    try {
      const bytes = await applySaveRequest(await readBytes(request.path), request)
      if (request.targetPath) {
        // Save As → create a new document (original untouched)
        await createDocument(request.targetPath, bytes)
      } else {
        const r = await putBytes(request.path, bytes)
        if (!r.ok) return { ok: false, error: `HTTP ${r.status}` }
      }
      return { ok: true }
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) }
    }
  },

  extractPages: async (request: ExtractPagesRequest): Promise<ExtractPagesResult> => {
    try {
      const out = await extractPagesBytes(await readBytes(request.path), request.pages)
      downloadBytes(request.suggestedName, out)
      return { ok: true, savedPath: request.suggestedName }
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) }
    }
  },

  insertPdf: async (request: InsertPdfRequest): Promise<InsertPdfResult> => {
    try {
      const other = await pickFile('.pdf,application/pdf')
      if (!other) return { ok: true, canceled: true }
      const { merged, count } = await insertPdfBytes(
        await readBytes(request.path),
        new Uint8Array(await other.arrayBuffer()),
        request.afterPageIndex,
      )
      const r = await putBytes(request.path, merged)
      if (!r.ok) return { ok: false, error: `HTTP ${r.status}` }
      return { ok: true, insertedCount: count }
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) }
    }
  },

  // renderer rasterizes the pages; the browser downloads each PNG (no dir dialog)
  exportImages: async (request: ExportImagesRequest): Promise<ExportImagesResult> => {
    try {
      request.images.forEach((b64, i) =>
        downloadBytes(`${request.baseName}-${request.pageNumbers[i]}.png`, b64ToBytes(b64)),
      )
      return { ok: true, savedDir: request.baseName, count: request.images.length }
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) }
    }
  },

  // close/save-as flow is shell-driven in Electron; the web relies on autosave + beforeunload
  setDirty: noop,
  onCloseSaveRequest: unsub,
  sendCloseSaveResult: noop,
  onSaveAsRequest: unsub,
  sendSaveAsResult: noop,
  onSaveAsFlow: unsub,

  getLanguage: async () => 'zh',
  onLanguageChanged: unsub,

  getAiSettings: async () =>
    ({ provider: 'backend' }) as unknown as Awaited<ReturnType<PdfApi['getAiSettings']>>,
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
}

// window.pdfApi type is declared in env.d.ts
window.pdfApi = api
