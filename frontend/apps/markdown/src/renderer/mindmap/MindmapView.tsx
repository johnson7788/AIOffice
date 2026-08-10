/**
 * Mind-map view: renders the current Markdown outline as an interactive
 * (zoom/pan/collapse) tree with markmap. The document model stays plain
 * Markdown — this is just a view of it, so AI edits via the normal markdown
 * tools reflect here automatically. ponytail: view-only, no drag-editing.
 */
import { useEffect, useRef } from 'react'
import type { Editor } from '@tiptap/core'
import { Transformer } from 'markmap-lib'
import { Markmap } from 'markmap-view'

const transformer = new Transformer()

export function MindmapView({ editor }: { editor: Editor | null }) {
  const svgRef = useRef<SVGSVGElement>(null)
  const mmRef = useRef<Markmap | null>(null)

  // create the markmap once, tear down on unmount
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const mm = Markmap.create(svg)
    mmRef.current = mm
    // markmap's d3-zoom reads svg.width/height.baseVal.value — a relative (%)
    // length throws "Could not resolve relative length". Mirror the flex-sized
    // box into absolute px width/height attributes so the zoom math resolves.
    const sync = () => {
      const box = svg.parentElement
      const w = box?.clientWidth ?? 0
      const h = box?.clientHeight ?? 0
      if (w > 0 && h > 0) {
        svg.setAttribute('width', String(w))
        svg.setAttribute('height', String(h))
      }
    }
    sync()
    // refit when the container resizes (view switch outline⇄split⇄mindmap, window)
    const ro = new ResizeObserver(() => {
      sync()
      void mm.fit()
    })
    if (svg.parentElement) ro.observe(svg.parentElement)
    return () => {
      ro.disconnect()
      mm.destroy()
      mmRef.current = null
    }
  }, [])

  // re-render whenever the document changes (AI or typing)
  useEffect(() => {
    if (!editor) return
    const render = () => {
      const mm = mmRef.current
      if (!mm) return
      try {
        const { root } = transformer.transform(editor.getMarkdown() || '')
        void mm.setData(root).then(() => mm.fit())
      } catch (err) {
        console.error('[markdown] mindmap transform failed:', err)
      }
    }
    render()
    editor.on('update', render)
    return () => {
      editor.off('update', render)
    }
  }, [editor])

  return <svg ref={svgRef} className="mindmap-svg" />
}
