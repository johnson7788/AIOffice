import { useState } from 'react'
import { authenticate } from '../web-adapter'

export function Login({ onAuthed }: { onAuthed: () => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    const r = await authenticate(email.trim(), password, mode)
    setBusy(false)
    if (r.ok) onAuthed()
    else setError(r.error ?? '登录失败')
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">AI Office</div>
        <div className="login-sub">{mode === 'login' ? '登录你的工作台' : '创建新账号'}</div>
        <input
          className="login-input"
          type="email"
          placeholder="邮箱"
          value={email}
          autoComplete="email"
          required
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          className="login-input"
          type="password"
          placeholder="密码"
          value={password}
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          required
          minLength={6}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <div className="login-error">{error}</div>}
        <button className="login-submit" type="submit" disabled={busy}>
          {busy ? '…' : mode === 'login' ? '登录' : '注册'}
        </button>
        <button
          type="button"
          className="login-switch"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login')
            setError('')
          }}
        >
          {mode === 'login' ? '没有账号？注册' : '已有账号？登录'}
        </button>
      </form>
    </div>
  )
}
