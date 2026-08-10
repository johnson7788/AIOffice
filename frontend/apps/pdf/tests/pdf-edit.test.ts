import { PDFDocument } from 'pdf-lib'
import { describe, expect, it } from 'vitest'
import {
  applySaveRequest,
  extractPagesBytes,
  insertPdfBytes,
} from '../src/renderer/adapter/pdf-edit'

async function blankPdf(pages: number): Promise<Uint8Array> {
  const doc = await PDFDocument.create()
  for (let i = 0; i < pages; i++) doc.addPage([200, 200])
  return doc.save({ useObjectStreams: false })
}

const emptyReq = { markups: [], drawings: [], formValues: [], stamps: [] }

describe('pdf-edit (ported pdf-lib core, browser-safe)', () => {
  it('applySaveRequest adds a highlight annotation', async () => {
    const src = await blankPdf(1)
    const out = await applySaveRequest(src, {
      path: 'x',
      ...emptyReq,
      markups: [{ pageIndex: 0, type: 'highlight', color: [1, 1, 0], quads: [[10, 10, 90, 10, 10, 30, 90, 30]] }],
    })
    const reloaded = await PDFDocument.load(out)
    expect(reloaded.getPageCount()).toBe(1)
    expect(out.length).toBeGreaterThan(src.length) // annotation added bytes
  })

  it('extractPagesBytes keeps only the requested pages', async () => {
    const out = await extractPagesBytes(await blankPdf(3), [0, 2])
    expect((await PDFDocument.load(out)).getPageCount()).toBe(2)
  })

  it('insertPdfBytes merges page counts', async () => {
    const { merged, count } = await insertPdfBytes(await blankPdf(2), await blankPdf(3), 0)
    expect(count).toBe(3)
    expect((await PDFDocument.load(merged)).getPageCount()).toBe(5)
  })

  it('applySaveRequest deletes and reorders pages', async () => {
    const out = await applySaveRequest(await blankPdf(3), {
      path: 'x',
      ...emptyReq,
      deletedPages: [1],
      pageOrder: [2, 0],
    })
    expect((await PDFDocument.load(out)).getPageCount()).toBe(2)
  })
})
