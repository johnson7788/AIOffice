import { useEffect, useState } from 'react'
import { type DocMeta, appUrl, clearToken, listDocuments } from '../web-adapter'

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

const KINDS: { id: Kind; label: string; disabled?: boolean }[] = [
  { id: 'docs', label: '文字文档' },
  { id: 'slides', label: '演示文稿' },
  { id: 'sheets', label: '表格' },
  { id: 'mindmap', label: '思维导图' },
]

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

  useEffect(() => {
    void listDocuments().then(setRecent)
  }, [])

  const send = () => {
    const text = prompt.trim()
    if (!text) return
    if (kind === 'slides') goSlides(text)
    else if (kind === 'sheets') goSheets(text)
    else if (kind === 'mindmap') goMindmap(text)
    else openWithPrompt(text, onOpenEditor)
  }

  return (
    <div className="home">
      <aside className="home-side">
        <div className="home-logo">AI Office</div>
        <div className="home-new-row">
          <button className="home-new" onClick={onOpenEditor}>
            + 文字文档
          </button>
          <button className="home-new" onClick={() => goSlides()}>
            + 演示文稿
          </button>
          <button className="home-new" onClick={() => goSheets()}>
            + 表格
          </button>
          <button className="home-new" onClick={() => goMindmap()}>
            + 思维导图
          </button>
        </div>
        <div className="home-side-title">最近</div>
        <div className="home-recent">
          {recent.length === 0 && <div className="home-empty">还没有文档</div>}
          {recent.map((d) => (
            <button key={d.id} className="home-recent-item" onClick={() => openDoc(d, onOpenEditor)}>
              {d.title}
            </button>
          ))}
        </div>
        <button className="home-logout" onClick={() => { clearToken(); location.reload() }}>
          退出登录
        </button>
      </aside>

      <main className="home-main">
        <h1 className="home-heading">想创建点什么？</h1>
        <div className="home-kind">
          {KINDS.map((k) => (
            <button
              key={k.id}
              className={`home-kind-btn${kind === k.id ? ' active' : ''}`}
              disabled={k.disabled}
              onClick={() => setKind(k.id)}
            >
              {k.label}
            </button>
          ))}
        </div>
        <div className="home-cards">
          {QUICK[kind].map((q) => (
            <button key={q.title} className="home-card" onClick={() => setPrompt(q.prompt)}>
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
        <div className="home-hint">Cmd/Ctrl + Enter 发送</div>
      </main>
    </div>
  )
}
