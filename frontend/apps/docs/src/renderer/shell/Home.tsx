import { useEffect, useMemo, useState } from 'react'
import {
  type DocMeta,
  type ProjectMeta,
  appUrl,
  clearToken,
  listDocuments,
  listProjects,
  projectDocIds,
} from '../web-adapter'

// A generation prompt is handed to the docs editor via sessionStorage; the docs
// App picks it up on boot and auto-runs the agent (see App.tsx boot effect).
function openWithPrompt(prompt: string, onOpen: () => void) {
  sessionStorage.setItem('aioffice.pendingPrompt', prompt)
  onOpen()
}
// Mind-map docs are Markdown, opened in the markdown app with the mind-map view on.
const isMindmap = (title: string) => /思维导图|脑图|\.mindmap\.md$/i.test(title)

function openDoc(doc: DocMeta, onOpen: () => void) {
  // Route by file type: pptx→slides, xlsx→sheets, mindmap md→markdown, else→docs.
  if (isMindmap(doc.title)) {
    const u = new URL(appUrl('markdown')) // appUrl already carries ?tok= in dev
    u.searchParams.set('doc', doc.id) // markdown app consumes ?doc=
    u.searchParams.set('view', 'mindmap')
    location.href = u.toString()
    return
  }
  const cross =
    /\.pptx$/i.test(doc.title) ? 'slides' : /\.(xlsx|xls|csv)$/i.test(doc.title) ? 'sheets' : null
  if (cross) {
    const u = new URL(appUrl(cross)) // appUrl already carries ?tok= in dev
    u.searchParams.set('open', doc.id)
    location.href = u.toString()
    return
  }
  sessionStorage.setItem('aioffice.pendingOpen', doc.id)
  onOpen()
}
// Other apps live on separate origins; hand the prompt over via ?gen= (works
// cross-origin in dev where sessionStorage wouldn't). `extra` carries e.g. ?view=.
function goApp(app: 'slides' | 'sheets' | 'markdown', prompt?: string, extra?: Record<string, string>) {
  const u = new URL(appUrl(app))
  if (prompt) u.searchParams.set('gen', prompt)
  for (const [k, v] of Object.entries(extra ?? {})) u.searchParams.set(k, v)
  location.href = u.toString()
}
const goSlides = (prompt?: string) => goApp('slides', prompt)
const goSheets = (prompt?: string) => goApp('sheets', prompt)
const goMindmap = (prompt?: string) => goApp('markdown', prompt, { view: 'mindmap' })

type Kind = 'docs' | 'slides' | 'sheets' | 'mindmap'

const KINDS: { id: Kind; label: string }[] = [
  { id: 'docs', label: '文字文档' },
  { id: 'slides', label: '演示文稿' },
  { id: 'sheets', label: '表格' },
  { id: 'mindmap', label: '思维导图' },
]

// Small type badge shown on recent cards / filter nav. `other` = pdf / plain md.
const BADGE: Record<Kind | 'other', { label: string; cls: string }> = {
  docs: { label: 'W', cls: 'k-docs' },
  slides: { label: 'P', cls: 'k-slides' },
  sheets: { label: 'X', cls: 'k-sheets' },
  mindmap: { label: '图', cls: 'k-mind' },
  other: { label: '·', cls: 'k-other' },
}

function docKind(doc: DocMeta): Kind | 'other' {
  if (isMindmap(doc.title)) return 'mindmap'
  switch (doc.type) {
    case 'docx':
      return 'docs'
    case 'pptx':
      return 'slides'
    case 'xlsx':
      return 'sheets'
    default:
      return 'other' // pdf / plain md
  }
}

function relTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const m = Math.floor(ms / 60000)
  if (m < 1) return '刚刚'
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  const d = Math.floor(h / 24)
  if (d < 30) return `${d} 天前`
  return new Date(iso).toLocaleDateString()
}

const QUICK: Record<Kind, { title: string; prompt: string }[]> = {
  docs: [
    { title: '写一份研究报告', prompt: '帮我写一份关于人工智能行业现状与趋势的研究报告，包含要点小节。' },
    { title: '起草商业计划', prompt: '帮我起草一份初创公司的商业计划书大纲，并展开第一部分。' },
    { title: '整理会议纪要', prompt: '把以下要点整理成结构化的会议纪要：' },
    { title: '润色一段文字', prompt: '帮我润色并改写下面这段文字，使其更专业：' },
  ],
  slides: [
    { title: '产品发布演示', prompt: '帮我做一份新产品发布的演示文稿，包含产品亮点、市场分析和路线图。' },
    { title: '项目汇报', prompt: '帮我做一份项目进展汇报的幻灯片，包含目标、进度、风险和下一步。' },
    { title: '培训课件', prompt: '帮我做一份面向新员工的入职培训课件。' },
    { title: '路演融资', prompt: '帮我做一份初创公司融资路演的 PPT 大纲。' },
  ],
  sheets: [
    { title: '月度预算表', prompt: '帮我做一份家庭月度预算表，包含收入、各项支出分类和结余合计。' },
    { title: '销售数据分析', prompt: '帮我做一份季度销售数据表，含各产品线销量、金额和环比增长率。' },
    { title: '项目进度跟踪', prompt: '帮我做一份项目任务进度跟踪表，含任务、负责人、截止日期和状态。' },
    { title: '财务三表模型', prompt: '帮我搭建一个简单的财务模型，包含利润表、资产负债表和现金流量表。' },
  ],
  mindmap: [
    { title: '知识梳理', prompt: '帮我用多级 Markdown 大纲梳理"机器学习基础"的知识框架，用作思维导图。' },
    { title: '项目规划', prompt: '帮我用层级 Markdown 大纲规划一个新产品从立项到上线的思维导图。' },
    { title: '读书笔记', prompt: '帮我把一本书的核心观点整理成多级 Markdown 大纲思维导图。' },
    { title: '头脑风暴', prompt: '围绕"提升团队效率"做一次头脑风暴，用层级 Markdown 大纲输出思维导图。' },
  ],
}

export function Home({ onOpenEditor }: { onOpenEditor: () => void }) {
  const [prompt, setPrompt] = useState('')
  const [kind, setKind] = useState<Kind>('docs')
  const [recent, setRecent] = useState<DocMeta[]>([])
  // filter = 'all' | a Kind | 'other' | `p:<projectId>`
  const [filter, setFilter] = useState<string>('all')
  const [query, setQuery] = useState('')
  const [projects, setProjects] = useState<ProjectMeta[]>([])
  // projectId → set of doc ids (from each project's chat timeline)
  const [projDocs, setProjDocs] = useState<Record<string, Set<string>>>({})

  useEffect(() => {
    void listDocuments().then(setRecent)
    void listProjects().then(async (ps) => {
      setProjects(ps)
      const map: Record<string, Set<string>> = {}
      await Promise.all(
        ps.map(async (p) => {
          map[p.id] = new Set(await projectDocIds(p.id))
        }),
      )
      setProjDocs(map)
    })
  }, [])

  // filter nav counts (by type + by project) derive from the recent list
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: recent.length }
    for (const d of recent) c[docKind(d)] = (c[docKind(d)] ?? 0) + 1
    for (const p of projects) c[`p:${p.id}`] = recent.filter((d) => projDocs[p.id]?.has(d.id)).length
    return c
  }, [recent, projects, projDocs])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    const inFilter = (d: DocMeta) => {
      if (filter === 'all') return true
      if (filter.startsWith('p:')) return projDocs[filter.slice(2)]?.has(d.id) ?? false
      return docKind(d) === filter
    }
    return recent.filter((d) => inFilter(d) && (!q || d.title.toLowerCase().includes(q)))
  }, [recent, filter, query, projDocs])

  const create = (k: Kind, text?: string) => {
    if (k === 'slides') goSlides(text)
    else if (k === 'sheets') goSheets(text)
    else if (k === 'mindmap') goMindmap(text)
    else if (text) openWithPrompt(text, onOpenEditor)
    else onOpenEditor()
  }

  const send = () => {
    const text = prompt.trim()
    if (text) create(kind, text)
  }

  const NAV: { id: string; label: string }[] = [
    { id: 'all', label: '全部' },
    ...KINDS.map((k) => ({ id: k.id, label: k.label })),
  ]
  const filterLabel =
    filter === 'all'
      ? '最近'
      : (NAV.find((n) => n.id === filter)?.label ??
        projects.find((p) => `p:${p.id}` === filter)?.name ??
        '文档')

  return (
    <div className="home">
      <aside className="home-side">
        <div className="home-logo">AI Office</div>
        <div className="home-new-row">
          <button className="home-new" onClick={() => create('docs')}>+ 文字</button>
          <button className="home-new" onClick={() => create('slides')}>+ 演示</button>
          <button className="home-new" onClick={() => create('sheets')}>+ 表格</button>
          <button className="home-new" onClick={() => create('mindmap')}>+ 导图</button>
        </div>
        <nav className="home-nav">
          {NAV.map((n) => (
            <button
              key={n.id}
              className={`home-nav-item${filter === n.id ? ' active' : ''}`}
              onClick={() => setFilter(n.id)}
            >
              <span>{n.label}</span>
              {counts[n.id] ? <span className="home-nav-count">{counts[n.id]}</span> : null}
            </button>
          ))}
        </nav>
        {projects.length > 0 && (
          <>
            <div className="home-nav-group">项目</div>
            <nav className="home-nav">
              {projects.map((p) => {
                const id = `p:${p.id}`
                return (
                  <button
                    key={p.id}
                    className={`home-nav-item${filter === id ? ' active' : ''}`}
                    onClick={() => setFilter(id)}
                  >
                    <span className="home-nav-name">{p.name}</span>
                    {counts[id] ? <span className="home-nav-count">{counts[id]}</span> : null}
                  </button>
                )
              })}
            </nav>
          </>
        )}
        <div className="home-side-spacer" />
        <button className="home-logout" onClick={() => { clearToken(); location.reload() }}>
          退出登录
        </button>
      </aside>

      <main className="home-main">
        <div className="home-topbar">
          <input
            className="home-search"
            placeholder="搜索文档…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        <section className="home-hero">
          <h1 className="home-heading">想创建点什么？</h1>
          <div className="home-kind">
            {KINDS.map((k) => (
              <button
                key={k.id}
                className={`home-kind-btn${kind === k.id ? ' active' : ''}`}
                onClick={() => setKind(k.id)}
              >
                {k.label}
              </button>
            ))}
          </div>
          <div className="home-cards">
            {QUICK[kind].map((q) => (
              <button key={q.title} className="home-card" onClick={() => create(kind, q.prompt)}>
                {q.title}
              </button>
            ))}
          </div>
          <div className="home-composer">
            <textarea
              className="home-input"
              placeholder={
                kind === 'slides'
                  ? '描述你想要的演示文稿，AI 会帮你生成 PPT…'
                  : kind === 'sheets'
                    ? '描述你想要的表格，AI 会帮你生成 Excel…'
                    : kind === 'mindmap'
                      ? '描述你想要的主题，AI 会帮你生成思维导图…'
                      : '描述你想创建的内容，AI 会帮你生成文档…'
              }
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send()
              }}
            />
            <button className="home-send" onClick={send} disabled={!prompt.trim()}>
              生成 →
            </button>
          </div>
          <div className="home-hint">Cmd/Ctrl + Enter 发送 · 点快捷卡片直接生成</div>
        </section>

        <section className="home-recent">
          <div className="home-recent-title">{filterLabel}</div>
          {shown.length === 0 ? (
            <div className="home-empty">{query ? '没有匹配的文档' : '还没有文档'}</div>
          ) : (
            <div className="home-grid">
              {shown.map((d) => {
                const b = BADGE[docKind(d)]
                return (
                  <button key={d.id} className="home-doc" onClick={() => openDoc(d, onOpenEditor)}>
                    <span className={`home-doc-badge ${b.cls}`}>{b.label}</span>
                    <span className="home-doc-title">{d.title}</span>
                    <span className="home-doc-time">{relTime(d.updated)}</span>
                  </button>
                )
              })}
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
