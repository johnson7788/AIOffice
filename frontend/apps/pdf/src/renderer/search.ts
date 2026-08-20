import type { PDFDocumentProxy } from 'pdfjs-dist'

/** One hit: original page + PDF user-space rects (multiple when spanning several text items) */
export interface SearchMatch {
  pageIndex: number
  rects: [number, number, number, number][]
}

interface IndexedItem {
  start: number
  end: number
  x: number
  y: number
  w: number
  h: number
}

export interface PageEntry {
  /** Original text (same length as lower; used for context excerpts) */
  text: string
  lower: string
  items: IndexedItem[]
  /** Whitespace-collapsed lower text (newlines/indent folded to single spaces), for tolerant citation matching */
  flat: string
  /** flat character index → original text character index */
  flatPos: number[]
}

export type SearchIndex = PageEntry[]

const MAX_MATCHES = 1000

interface RawTextItem {
  str?: string
  transform?: number[]
  width?: number
  height?: number
  hasEOL?: boolean
}

/** Collapse every whitespace run to a single space, recording each kept char's original index */
function collapseSpaces(text: string): { flat: string; flatPos: number[] } {
  let flat = ''
  const flatPos: number[] = []
  let inSpace = false
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]!
    if (/\s/.test(ch)) {
      if (flat.length > 0 && !inSpace) {
        flat += ' '
        flatPos.push(i) // the collapsed space token maps to the first whitespace char of the run
      }
      inSpace = true
      continue
    }
    inSpace = false
    flat += ch
    flatPos.push(i)
  }
  return { flat, flatPos }
}

/** Rectangles (PDF space) covering char range [s, e) across the page's indexed items */
function rectsInRange(
  items: IndexedItem[],
  s: number,
  e: number,
): [number, number, number, number][] {
  const rects: [number, number, number, number][] = []
  for (const it of items) {
    if (it.end <= s || it.start >= e) continue
    const len = it.end - it.start
    const lo = (Math.max(s, it.start) - it.start) / len
    const hi = (Math.min(e, it.end) - it.start) / len
    const x1 = it.x + it.w * lo
    const x2 = it.x + it.w * hi
    if (x2 - x1 < 0.01) continue
    rects.push([x1, it.y, x2, it.y + it.h])
  }
  return rects
}

/** Concatenate text per page + record each item's char range and PDF-space box (built once, cached per doc by caller) */
export async function buildSearchIndex(doc: PDFDocumentProxy): Promise<SearchIndex> {
  const entries: PageEntry[] = []
  for (let n = 1; n <= doc.numPages; n++) {
    const page = await doc.getPage(n)
    const content = await page.getTextContent()
    let text = ''
    const items: IndexedItem[] = []
    for (const it of content.items as RawTextItem[]) {
      if (typeof it.str !== 'string') continue
      if (it.str.length > 0 && it.transform) {
        const h = it.height || Math.hypot(it.transform[2] ?? 0, it.transform[3] ?? 0)
        items.push({
          start: text.length,
          end: text.length + it.str.length,
          x: it.transform[4] ?? 0,
          y: it.transform[5] ?? 0,
          w: it.width ?? 0,
          h,
        })
        text += it.str
      }
      if (it.hasEOL) text += '\n'
    }
    const lower = text.toLowerCase()
    const { flat, flatPos } = collapseSpaces(lower)
    entries.push({ text, lower, items, flat, flatPos })
  }
  return entries
}

/** Case-insensitive full-text search; rects linearly interpolated within items by char ratio (approximate; bounding box for rotated glyphs) */
export function searchInIndex(index: SearchIndex, query: string): SearchMatch[] {
  const q = query.toLowerCase()
  if (!q) return []
  const matches: SearchMatch[] = []
  for (let pageIndex = 0; pageIndex < index.length; pageIndex++) {
    const { lower, items } = index[pageIndex]!
    let from = 0
    while (matches.length < MAX_MATCHES) {
      const s = lower.indexOf(q, from)
      if (s < 0) break
      const e = s + q.length
      from = e
      const rects = rectsInRange(items, s, e)
      if (rects.length > 0) matches.push({ pageIndex, rects })
    }
    if (matches.length >= MAX_MATCHES) break
  }
  return matches
}

/**
 * Locate a cited passage in the index, tolerant of the model's minor wording
 * drift. Tries, in order: exact case-insensitive match, progressively dropping
 * trailing words, then a whitespace-collapsed match (so a quote spanning a line
 * break still resolves). Returns every occurrence across the whole document.
 */
export function locateInIndex(index: SearchIndex, text: string): SearchMatch[] {
  const q = text.trim()
  if (!q) return []

  const exact = searchInIndex(index, q)
  if (exact.length > 0) return exact

  // Fallback 1: the model sometimes appends a stray word — drop trailing words.
  const words = q.split(/\s+/)
  for (let n = 1; n < words.length; n++) {
    const head = words.slice(0, words.length - n).join(' ')
    if (head.length < 3) break
    const m = searchInIndex(index, head)
    if (m.length > 0) return m
  }

  // Fallback 2: whitespace/newline tolerant match on the collapsed page text.
  const flatQuery = collapseSpaces(q.toLowerCase()).flat
  if (flatQuery.length < 3) return []
  const matches: SearchMatch[] = []
  for (let pageIndex = 0; pageIndex < index.length; pageIndex++) {
    const entry = index[pageIndex]!
    let from = 0
    while (matches.length < MAX_MATCHES) {
      const idx = entry.flat.indexOf(flatQuery, from)
      if (idx < 0) break
      const s = entry.flatPos[idx]!
      const e = entry.flatPos[idx + flatQuery.length - 1]! + 1
      from = idx + 1
      const rects = rectsInRange(entry.items, s, e)
      if (rects.length > 0) matches.push({ pageIndex, rects })
    }
    if (matches.length >= MAX_MATCHES) break
  }
  return matches
}