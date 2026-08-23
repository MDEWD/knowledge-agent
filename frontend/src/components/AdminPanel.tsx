import { useEffect, useState } from 'react'
import { fetchAdminUsers, fetchAuthAuditLogs, revokeAdminUserSessions, updateAdminUser } from '../api/client'
import type { AdminUser, AuthAuditLog, AuthUser } from '../types'

interface Props {
  currentUser: AuthUser
}

const statusLabel: Record<string, string> = { active: '正常', pending: '待验证', suspended: '已停用' }
const statusStyle: Record<string, string> = {
  active: 'admin-status-active bg-emerald-900/40 text-emerald-300',
  pending: 'admin-status-pending bg-amber-900/40 text-amber-300',
  suspended: 'admin-status-suspended bg-red-900/40 text-red-300',
}
const roleOptions = [
  { value: '', label: '全部角色' },
  { value: 'user', label: '普通用户' },
  { value: 'admin', label: '管理员' },
]
const userRoleOptions = roleOptions.slice(1)
const statusOptions = [
  { value: '', label: '全部状态' },
  { value: 'active', label: '正常' },
  { value: 'pending', label: '待验证' },
  { value: 'suspended', label: '已停用' },
]

interface CompactSelectProps {
  ariaLabel: string
  value: string
  options: Array<{ value: string; label: string }>
  onChange: (value: string) => void
  compact?: boolean
  disabled?: boolean
}

function CompactSelect({ ariaLabel, value, options, onChange, compact = false, disabled = false }: CompactSelectProps) {
  const selectedLabel = options.find((option) => option.value === value)?.label ?? value

  return (
    <span className={`admin-compact-select relative inline-flex items-center gap-1 rounded-xl border border-gray-700 bg-gray-900/50 text-gray-300 transition focus-within:border-cyan-500 focus-within:ring-2 focus-within:ring-cyan-500/10 ${compact ? 'px-2.5 py-2 text-xs' : 'w-full px-4 py-3 text-sm md:w-auto'} ${disabled ? 'opacity-40' : 'cursor-pointer'}`}>
      <span>{selectedLabel}</span>
      <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className="h-3.5 w-3.5 shrink-0 text-gray-500">
        <path d="m6 8 4 4 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <select aria-label={ariaLabel} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed">
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </span>
  )
}

export default function AdminPanel({ currentUser }: Props) {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [logs, setLogs] = useState<AuthAuditLog[]>([])
  const [total, setTotal] = useState(0)
  const [query, setQuery] = useState('')
  const [role, setRole] = useState('')
  const [status, setStatus] = useState('')
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const activeFilterCount = Number(Boolean(query.trim())) + Number(Boolean(role)) + Number(Boolean(status))

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [result, audit] = await Promise.all([
        fetchAdminUsers({ q: query, role, status }),
        fetchAuthAuditLogs(),
      ])
      setUsers(result.users)
      setTotal(result.total)
      setLogs(audit)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '用户数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [role, status])

  const mutate = async (user: AdminUser, patch: { role?: string; status?: string }) => {
    setBusyId(user.id)
    setError('')
    setMessage('')
    try {
      await updateAdminUser(user.id, patch)
      setMessage('用户设置已更新')
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '操作失败')
    } finally {
      setBusyId('')
    }
  }

  const revoke = async (user: AdminUser) => {
    if (!window.confirm(`确认撤销 ${user.email} 的所有登录会话？`)) return
    setBusyId(user.id)
    try {
      const count = await revokeAdminUserSessions(user.id)
      setMessage(`已撤销 ${count} 个会话`)
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '会话撤销失败')
    } finally {
      setBusyId('')
    }
  }

  return (
    <div className="admin-panel mx-auto flex h-full w-full max-w-7xl flex-col gap-4 overflow-y-auto pb-6 md:gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><h2 className="text-xl font-semibold text-white">用户管理</h2><p className="mt-1 text-sm text-gray-500">管理账户状态、管理员权限和登录会话</p></div>
        <span className="rounded-full border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-400">共 {total} 位用户</span>
      </div>

      <div className="md:hidden">
        <button type="button" aria-expanded={mobileFiltersOpen} onClick={() => setMobileFiltersOpen((open) => !open)} className="admin-mobile-filter-toggle flex w-full items-center justify-between rounded-xl border border-gray-700 bg-gray-900/50 px-4 py-3 text-sm text-gray-400">
          <span className="flex items-center gap-2">
            <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className="h-4 w-4"><path d="M3 5h14M6 10h8m-5 5h2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>
            搜索与筛选
            {activeFilterCount > 0 && <span className="rounded-full bg-cyan-600 px-1.5 py-0.5 text-[10px] text-white">{activeFilterCount}</span>}
          </span>
          <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className={`h-4 w-4 transition-transform ${mobileFiltersOpen ? 'rotate-180' : ''}`}><path d="m6 8 4 4 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </button>
        {mobileFiltersOpen && <div className="admin-mobile-filters admin-surface admin-filter-surface mt-2 grid gap-2 rounded-xl border border-gray-800 bg-gray-800/40 p-3">
          <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void load()} placeholder="搜索邮箱或昵称" className="auth-input" />
          <div className="flex flex-wrap gap-2">
            <CompactSelect ariaLabel="筛选用户角色" value={role} options={roleOptions} onChange={setRole} />
            <CompactSelect ariaLabel="筛选用户状态" value={status} options={statusOptions} onChange={setStatus} />
          </div>
          <button onClick={() => { void load(); setMobileFiltersOpen(false) }} className="rounded-xl bg-cyan-600 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-cyan-500">查询</button>
        </div>}
      </div>

      <div className="admin-surface admin-filter-surface hidden gap-3 rounded-2xl border border-gray-800 bg-gray-800/40 p-4 md:grid md:grid-cols-[1fr_auto_auto_auto]">
        <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void load()} placeholder="搜索邮箱或昵称" className="auth-input" />
        <CompactSelect ariaLabel="筛选用户角色" value={role} options={roleOptions} onChange={setRole} />
        <CompactSelect ariaLabel="筛选用户状态" value={status} options={statusOptions} onChange={setStatus} />
        <button onClick={() => void load()} className="rounded-xl bg-cyan-600 px-5 py-3 text-sm font-medium text-white transition hover:bg-cyan-500">查询</button>
      </div>

      {message && <div className="rounded-xl border border-emerald-800 bg-emerald-950/30 px-4 py-3 text-sm text-emerald-300">{message}</div>}
      {error && <div className="rounded-xl border border-red-800 bg-red-950/30 px-4 py-3 text-sm text-red-300">{error}</div>}

      <div className="admin-mobile-users space-y-3 md:hidden">
        {loading && <div className="admin-surface rounded-xl border border-gray-800 bg-gray-800/30 px-4 py-8 text-center text-sm text-gray-500">正在加载用户…</div>}
        {!loading && users.map((user) => {
          const self = user.id === currentUser.id
          const disabled = self || busyId === user.id
          return <article key={user.id} className="admin-surface rounded-2xl border border-gray-800 bg-gray-800/30 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0"><h3 className="truncate font-medium text-gray-200">{user.display_name || '未命名'}</h3><p className="mt-1 truncate text-xs text-gray-500">{user.email || user.id}</p></div>
              <div className="shrink-0 text-right"><span className={`admin-status-badge rounded-full px-2.5 py-1 text-xs ${statusStyle[user.status] || statusStyle.pending}`}>{statusLabel[user.status] || user.status}</span><p className="mt-2 text-[11px] text-gray-600">{user.email_verified ? '邮箱已验证' : '邮箱未验证'}</p></div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 border-y border-gray-800 py-3">
              <div><p className="mb-2 text-[11px] text-gray-600">角色</p><CompactSelect compact disabled={disabled} ariaLabel={`设置 ${user.email || user.id} 的角色`} value={user.role} options={userRoleOptions} onChange={(value) => void mutate(user, { role: value })} /></div>
              <div><p className="text-[11px] text-gray-600">活跃会话</p><p className="mt-2 text-sm text-gray-300">{user.session_count}</p><p className="mt-1 text-[11px] text-gray-600">{user.last_seen_at ? new Date(user.last_seen_at).toLocaleString() : '暂无记录'}</p></div>
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <p className="text-[11px] text-gray-500">注册于 {user.created_at ? new Date(user.created_at).toLocaleDateString() : '-'}</p>
              <div className="flex gap-2">{user.status === 'active' ? <button disabled={disabled} onClick={() => void mutate(user, { status: 'suspended' })} className="rounded-lg border border-red-900 px-3 py-2 text-xs text-red-400 disabled:opacity-30">停用</button> : user.email_verified && <button disabled={disabled} onClick={() => void mutate(user, { status: 'active' })} className="rounded-lg border border-emerald-900 px-3 py-2 text-xs text-emerald-400 disabled:opacity-30">启用</button>}<button disabled={disabled} onClick={() => void revoke(user)} className="rounded-lg border border-gray-700 px-3 py-2 text-xs text-gray-400 disabled:opacity-30">下线会话</button></div>
            </div>
          </article>
        })}
        {!loading && users.length === 0 && <div className="admin-surface rounded-xl border border-gray-800 bg-gray-800/30 px-4 py-10 text-center text-sm text-gray-600">没有符合条件的用户</div>}
      </div>

      <div className="admin-desktop-users admin-surface hidden overflow-x-auto rounded-2xl border border-gray-800 bg-gray-800/30 md:block">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="border-b border-gray-800 text-xs uppercase tracking-wide text-gray-500"><tr><th className="px-5 py-4">用户</th><th className="px-4 py-4">验证/状态</th><th className="px-4 py-4">角色</th><th className="px-4 py-4">活跃会话</th><th className="px-4 py-4">注册时间</th><th className="px-5 py-4 text-right">操作</th></tr></thead>
          <tbody className="divide-y divide-gray-800">
            {users.map((user) => {
              const self = user.id === currentUser.id
              const disabled = self || busyId === user.id
              return <tr key={user.id} className="admin-table-row text-gray-300 hover:bg-gray-800/40">
                <td className="px-5 py-4"><p className="font-medium text-gray-200">{user.display_name || '未命名'}</p><p className="mt-1 text-xs text-gray-500">{user.email || user.id}</p></td>
                <td className="px-4 py-4"><span className={`admin-status-badge rounded-full px-2.5 py-1 text-xs ${statusStyle[user.status] || statusStyle.pending}`}>{statusLabel[user.status] || user.status}</span><p className="mt-2 text-xs text-gray-600">{user.email_verified ? '邮箱已验证' : '邮箱未验证'}</p></td>
                <td className="px-4 py-4"><CompactSelect compact disabled={disabled} ariaLabel={`设置 ${user.email || user.id} 的角色`} value={user.role} options={userRoleOptions} onChange={(value) => void mutate(user, { role: value })} /></td>
                <td className="px-4 py-4"><p>{user.session_count}</p><p className="mt-1 text-xs text-gray-600">{user.last_seen_at ? new Date(user.last_seen_at).toLocaleString() : '暂无记录'}</p></td>
                <td className="px-4 py-4 text-xs text-gray-500">{user.created_at ? new Date(user.created_at).toLocaleDateString() : '-'}</td>
                <td className="px-5 py-4"><div className="flex justify-end gap-2">{user.status === 'active' ? <button disabled={disabled} onClick={() => void mutate(user, { status: 'suspended' })} className="rounded-lg border border-red-900 px-3 py-2 text-xs text-red-400 hover:bg-red-950/40 disabled:opacity-30">停用</button> : user.email_verified && <button disabled={disabled} onClick={() => void mutate(user, { status: 'active' })} className="rounded-lg border border-emerald-900 px-3 py-2 text-xs text-emerald-400 hover:bg-emerald-950/40 disabled:opacity-30">启用</button>}<button disabled={disabled} onClick={() => void revoke(user)} className="rounded-lg border border-gray-700 px-3 py-2 text-xs text-gray-400 hover:bg-gray-800 disabled:opacity-30">下线会话</button></div></td>
              </tr>
            })}
            {!loading && users.length === 0 && <tr><td colSpan={6} className="px-5 py-12 text-center text-gray-600">没有符合条件的用户</td></tr>}
          </tbody>
        </table>
        {loading && <div className="px-5 py-8 text-center text-sm text-gray-500">正在加载用户…</div>}
      </div>

      <section className="admin-surface rounded-2xl border border-gray-800 bg-gray-800/30 p-5">
        <h3 className="font-medium text-gray-200">最近管理操作</h3>
        <div className="mt-4 space-y-2">{logs.slice(0, 12).map((log) => <div key={log.id} className="admin-audit-row flex flex-wrap items-center justify-between gap-2 rounded-xl bg-gray-900/50 px-4 py-3 text-xs text-gray-500"><span><strong className="font-medium text-gray-300">{log.actor_email || '系统'}</strong> · {log.action} · {log.target_email || '-'}</span><span>{new Date(log.created_at).toLocaleString()}</span></div>)}{logs.length === 0 && <p className="py-4 text-sm text-gray-600">暂无审计记录</p>}</div>
      </section>
    </div>
  )
}
