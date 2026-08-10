import { useEffect, useRef, useState } from 'react'

export interface GalleryImage {
  title: string
  imageUrl: string
  sourceUrl?: string
  source?: string
  width?: number
  height?: number
}

export interface ImageGalleryProps {
  /** Runs the actual web image search — each app passes its own adapter (e.g. slidesApi.imageSearch). */
  search: (query: string, max?: number) => Promise<{ images: GalleryImage[] }>
  /** Called with the chosen image; the app decides how to insert it. */
  onPick: (image: GalleryImage) => void
  onClose?: () => void
  /** Optional seed query run on mount. */
  initialQuery?: string
  placeholder?: string
}

// ponytail: layout via inline styles so it drops into any app with zero per-app CSS.
// Add className hooks only if a designer wants to reskin it later.
export function ImageGallery({ search, onPick, onClose, initialQuery = '', placeholder }: ImageGalleryProps) {
  const [query, setQuery] = useState(initialQuery)
  const [images, setImages] = useState<GalleryImage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const seq = useRef(0)

  async function run(q: string) {
    const term = q.trim()
    if (!term) return
    const my = ++seq.current
    setLoading(true)
    setError('')
    try {
      const res = await search(term, 24)
      if (my !== seq.current) return // stale
      setImages(res.images ?? [])
      if (!res.images?.length) setError('没有找到相关图片')
    } catch {
      if (my === seq.current) setError('图片搜索失败')
    } finally {
      if (my === seq.current) setLoading(false)
    }
  }

  useEffect(() => {
    if (initialQuery.trim()) void run(initialQuery)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div style={S.panel}>
      <div style={S.bar}>
        <input
          style={S.input}
          value={query}
          placeholder={placeholder ?? '搜索图片…'}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void run(query)
          }}
          autoFocus
        />
        <button style={S.btn} onClick={() => void run(query)} disabled={loading}>
          {loading ? '搜索中…' : '搜索'}
        </button>
        {onClose && (
          <button style={S.close} onClick={onClose} aria-label="关闭">
            ×
          </button>
        )}
      </div>
      {error && <div style={S.hint}>{error}</div>}
      <div style={S.grid}>
        {images.map((img, i) => (
          <button
            key={`${img.imageUrl}-${i}`}
            style={S.cell}
            title={img.title || img.source || ''}
            onClick={() => onPick(img)}
          >
            <img src={img.imageUrl} alt={img.title || ''} style={S.thumb} loading="lazy" />
          </button>
        ))}
      </div>
    </div>
  )
}

const S: Record<string, React.CSSProperties> = {
  panel: { display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, gap: 8, padding: 12 },
  bar: { display: 'flex', gap: 8, alignItems: 'center' },
  input: {
    flex: 1,
    padding: '6px 10px',
    borderRadius: 8,
    border: '1px solid var(--border, #d0d5dd)',
    fontSize: 14,
    outline: 'none',
  },
  btn: {
    padding: '6px 14px',
    borderRadius: 8,
    border: 'none',
    background: 'var(--accent, #2563eb)',
    color: '#fff',
    fontSize: 14,
    cursor: 'pointer',
  },
  close: { border: 'none', background: 'transparent', fontSize: 22, lineHeight: 1, cursor: 'pointer', color: '#667085' },
  hint: { fontSize: 13, color: '#667085', padding: '4px 2px' },
  grid: {
    flex: 1,
    minHeight: 0,
    overflowY: 'auto',
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
    gap: 8,
    alignContent: 'start',
  },
  cell: {
    padding: 0,
    border: '1px solid var(--border, #eaecf0)',
    borderRadius: 8,
    overflow: 'hidden',
    cursor: 'pointer',
    background: '#f9fafb',
    aspectRatio: '4 / 3',
  },
  thumb: { width: '100%', height: '100%', objectFit: 'cover', display: 'block' },
}
