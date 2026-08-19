import { FormEvent, useState } from 'react'
import {
  loginWithEmail,
  registerWithEmail,
  requestPasswordReset,
  resendVerificationCode,
  resetPasswordWithCode,
  verifyEmailCode,
} from '../api/client'
import type { AuthUser } from '../types'

interface Props {
  onAuthenticated: (user: AuthUser) => void
  isDark: boolean
  onToggleTheme: () => void
}

type Mode = 'login' | 'register' | 'verify' | 'forgot' | 'reset'

const copy: Record<Mode, { eyebrow: string; title: string; hint: string; action: string }> = {
  login: { eyebrow: '欢迎回来', title: '登录你的账户', hint: '继续之前的对话和深度研究。', action: '登录' },
  register: { eyebrow: '创建研究空间', title: '注册新账户', hint: '注册后需要验证邮箱。', action: '创建账户' },
  verify: { eyebrow: '验证邮箱', title: '输入 6 位验证码', hint: '验证码 10 分钟内有效。', action: '完成验证' },
  forgot: { eyebrow: '找回密码', title: '获取重置验证码', hint: '我们会向已注册邮箱发送验证码。', action: '发送验证码' },
  reset: { eyebrow: '设置新密码', title: '重置账户密码', hint: '重置后其他登录会话会立即失效。', action: '重置密码' },
}

export default function AuthPage({ onAuthenticated, isDark, onToggleTheme }: Props) {
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [code, setCode] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const go = (next: Mode) => {
    setMode(next)
    setError('')
    setNotice('')
    setPassword('')
    setCode('')
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setError('')
    setNotice('')
    const normalizedEmail = email.trim()
    try {
      if (mode === 'login') {
        onAuthenticated(await loginWithEmail(normalizedEmail, password))
      } else if (mode === 'register') {
        const result = await registerWithEmail(normalizedEmail, password, displayName.trim())
        setMode('verify')
        setPassword('')
        setNotice(result.message + (result.dev_code ? `，开发验证码：${result.dev_code}` : ''))
      } else if (mode === 'verify') {
        onAuthenticated(await verifyEmailCode(normalizedEmail, code))
      } else if (mode === 'forgot') {
        const result = await requestPasswordReset(normalizedEmail)
        setMode('reset')
        setNotice(result.message)
      } else {
        const result = await resetPasswordWithCode(normalizedEmail, code, password)
        setMode('login')
        setCode('')
        setPassword('')
        setNotice(result.message)
      }
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '请求失败，请稍后重试'
      setError(message)
      if (mode === 'login' && message.includes('邮箱验证')) setMode('verify')
    } finally {
      setSubmitting(false)
    }
  }

  const resend = async () => {
    if (!email.trim() || submitting) return
    setSubmitting(true)
    setError('')
    try {
      const result = await resendVerificationCode(email.trim())
      setNotice(result.message + (result.dev_code ? `，开发验证码：${result.dev_code}` : ''))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '验证码发送失败')
    } finally {
      setSubmitting(false)
    }
  }

  const current = copy[mode]
  const needsPassword = mode === 'login' || mode === 'register' || mode === 'reset'
  const needsCode = mode === 'verify' || mode === 'reset'

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gray-900 px-5 py-10 text-white">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -left-32 top-[-8rem] h-96 w-96 rounded-full bg-cyan-500/10 blur-3xl" />
        <div className="absolute -right-32 bottom-[-10rem] h-[28rem] w-[28rem] rounded-full bg-blue-600/10 blur-3xl" />
      </div>

      <button type="button" onClick={onToggleTheme} className="absolute right-6 top-5 rounded-xl border border-gray-700 bg-gray-800/60 px-3 py-2 text-sm text-gray-300 transition hover:border-gray-600 hover:text-white">
        {isDark ? '☀️' : '🌙'}
      </button>

      <section className="relative grid w-full max-w-5xl overflow-hidden rounded-3xl border border-gray-800 bg-gray-800/50 shadow-2xl shadow-black/20 backdrop-blur-xl md:grid-cols-[1.08fr_0.92fr]">
        <div className="auth-brand-panel hidden min-h-[650px] flex-col justify-between border-r border-gray-800 bg-gradient-to-br from-cyan-950/40 via-gray-900/30 to-blue-950/40 p-12 md:flex">
          <div>
            <div className="auth-brand-icon mb-8 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-cyan-400 to-blue-600 text-xl shadow-lg shadow-cyan-900/30">✦</div>
            <p className="auth-brand-eyebrow mb-3 text-xs font-semibold uppercase tracking-[0.28em] text-cyan-400">Multi-Agent Research</p>
            <h1 className="auth-brand-title max-w-md text-4xl font-semibold leading-tight">多智能体研究工作台</h1>
            <p className="auth-brand-copy mt-5 max-w-md text-sm leading-7 text-gray-400">将本地内容、RAG 检索与长周期 DeepResearch 放进同一个可验证、可恢复的研究空间。</p>
          </div>
          <div className="auth-brand-features space-y-4 text-sm text-gray-400">
            {[
              ['结构化证据', 'Evidence 与正文引用可追溯'],
              ['多 Agent 协作', 'Supervisor 驱动规划、研究与评估'],
              ['安全身份空间', '邮箱验证与用户数据隔离'],
            ].map(([title, detail]) => (
              <div key={title} className="flex items-start gap-3"><span className="auth-brand-dot mt-1 h-2 w-2 shrink-0 rounded-full bg-cyan-400" /><div><strong className="font-medium text-gray-200">{title}</strong><span className="ml-2">{detail}</span></div></div>
            ))}
          </div>
        </div>

        <div className="flex min-h-[650px] flex-col justify-center p-7 sm:p-11">
          <div className="mb-7">
            <p className="text-sm font-medium text-cyan-400">{current.eyebrow}</p>
            <h2 className="mt-2 text-2xl font-semibold">{current.title}</h2>
            <p className="mt-2 text-sm text-gray-500">{current.hint}</p>
          </div>

          <form className="space-y-4" onSubmit={submit}>
            {mode === 'register' && (
              <Field label="昵称"><input value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={120} autoComplete="name" placeholder="怎么称呼你" className="auth-input" /></Field>
            )}
            <Field label="邮箱"><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" placeholder="name@example.com" className="auth-input" /></Field>
            {needsCode && (
              <Field label="验证码"><input inputMode="numeric" required pattern="[0-9]{6}" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} autoComplete="one-time-code" placeholder="6 位数字验证码" className="auth-input tracking-[0.35em]" /></Field>
            )}
            {needsPassword && (
              <Field label={mode === 'reset' ? '新密码' : '密码'}><input type="password" required minLength={8} maxLength={128} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} placeholder={mode === 'login' ? '输入密码' : '至少 8 位，同时包含字母和数字'} className="auth-input" /></Field>
            )}

            {notice && <div className="rounded-xl border border-cyan-800/70 bg-cyan-950/30 px-4 py-3 text-sm leading-6 text-cyan-200">{notice}</div>}
            {error && <div className="rounded-xl border border-red-800 bg-red-900/20 px-4 py-3 text-sm text-red-300" role="alert">{error}</div>}

            <button type="submit" disabled={submitting} className="w-full rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 px-4 py-3 text-sm font-semibold shadow-lg shadow-cyan-950/30 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50">
              {submitting ? '请稍候…' : current.action}
            </button>
          </form>

          <div className="mt-6 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-sm">
            {mode === 'login' && <><button onClick={() => go('forgot')} className="text-gray-500 hover:text-gray-300">忘记密码</button><button onClick={() => go('register')} className="font-medium text-cyan-400 hover:text-cyan-300">立即注册</button></>}
            {mode === 'register' && <button onClick={() => go('login')} className="text-cyan-400 hover:text-cyan-300">返回登录</button>}
            {mode === 'verify' && <><button onClick={() => void resend()} disabled={submitting} className="text-cyan-400 disabled:opacity-40">重新发送</button><button onClick={() => go('login')} className="text-gray-500 hover:text-gray-300">返回登录</button></>}
            {(mode === 'forgot' || mode === 'reset') && <button onClick={() => go('login')} className="text-gray-500 hover:text-gray-300">返回登录</button>}
          </div>
        </div>
      </section>
    </main>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block"><span className="mb-2 block text-sm text-gray-300">{label}</span>{children}</label>
}
