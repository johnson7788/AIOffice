import { describe, expect, it } from 'vitest'
import { createBlankPptx, openPptx } from '@genoffice/pptx-engine'
import { buildRenderSlide } from '@genoffice/pptx-render'

// M4.2 foundation: the pptx engine (parse) + render layer both run client-side in
// the browser (here: jsdom). This is the pipeline the slides web-adapter wraps —
// open bytes -> OpenedPptx -> per-slide RenderSlide -> Konva canvas.
describe('slides browser pptx pipeline', () => {
  it('creates, opens, and renders a blank deck without Node/electron', async () => {
    const bytes = await createBlankPptx()
    expect(bytes.byteLength).toBeGreaterThan(0)

    const opened = await openPptx(bytes)
    expect(opened.deck.slides.length).toBeGreaterThanOrEqual(1)
    expect(opened.deck.size.cx).toBeGreaterThan(0)

    const rs = buildRenderSlide(opened.deck.slides[0]!, opened.deck.size, { fitWidthPx: 960 })
    expect(rs).toBeTruthy()
    expect(Array.isArray(rs.nodes)).toBe(true)
  })

  // M4.3: the web-adapter installs window.slidesApi over the same engine +
  // module-level Session. Exercise the session/history path (newBlank ->
  // addBlankSlide -> undo) without touching the backend blob store.
  it('web-adapter session drives new/add/undo through slidesApi', async () => {
    await import('../src/renderer/web-adapter')
    const api = window.slidesApi

    const opened = await api.newBlank(960)
    expect(opened).toBeTruthy()
    const n0 = opened!.slides.length

    const added = await api.addBlankSlide({ sourceIndex: 0, fitWidthPx: 960 })
    expect(added!.slides.length).toBe(n0 + 1)

    const undone = await api.undo()
    expect(undone!.length).toBe(n0)
  })
})
