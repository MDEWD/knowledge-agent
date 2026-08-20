import { useEffect, useState } from 'react'
import { fetchAdminUsers, fetchAuthAuditLogs, revokeAdminUserSessions, updateAdminUser } from '../api/client'
import type { AdminUser, AuthAuditLog, AuthUser } from '../types'

interface Props {
  currentUser: AuthUser
}

const statusLabel: Record<string, string> = { active: '正常', pending: '待验证', suspended: '已停用' }

export default function AdminPanel({ currentUser }: Props) {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [logs, setLogs] = useState<AuthAuditLog[]>([])
  const [total, setTotal] = useState(0)
  const [query, setQuery] = useState('')
  const [role, setRole] = useState('')
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

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
    <div className="mx-auto flex h-full w-full max-w-7xl flex-col gap-5 overflow-y-auto pb-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><h2 className="text-xl font-semibold text-white">用户管理</h2><p className="mt-1 text-sm text-gray-500">管理账户状态、管理员权限和登录会话</p></div>
        <span className="rounded-full border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-400">共 {total} 位用户</span>
      </div>

      <div className="grid gap-3 rounded-2xl border border-gray-800 bg-gray-800/40 p-4 md:grid-cols-[1fr_160px_160px_auto]">
        <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void load()} placeholder="搜索邮箱或昵称" className="auth-input" />
        <select value={role} onChange={(e) => setRole(e.target.value)} className="auth-input"><option value="">全部角色</option><option value="user">普通用户</option><option value="admin">管理员</option></select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="auth-input"><option value="">全部状态</option><option value="active">正常</option><option value="pending">待验证</option><option value="suspended">已停用</option></select>
        <button onClick={() => void load()} className="rounded-xl bg-cyan-600 px-5 py-3 text-sm font-medium text-white transition hover:bg-cyan-500">查询</button>
      </div>

      {message && <div className="rounded-xl border border-emerald-800 bg-emerald-950/30 px-4 py-3 text-sm text-emerald-300">{message}</div>}
      {error && <div className="rounded-xl border border-red-800 bg-red-950/30 px-4 py-3 text-sm text-red-300">{error}</div>}

      <div className="overflow-x-auto rounded-2xl border border-gray-800 bg-gray-800/30">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="border-b border-gray-800 text-xs uppercase tracking-wide text-gray-500"><tr><th className="px-5 py-4">用户</th><th className="px-4 py-4">验证/状态</th><th className="px-4 py-4">角色</th><th className="px-4 py-4">活跃会话</th><th className="px-4 py-4">注册时间</th><th className="px-5 py-4 text-right">操作</th></tr></thead>
          <tbody className="divide-y divide-gray-800">
            {users.map((user) => {
              const self = user.id === currentUser.id
              const disabled = self || busyId === user.id
              return <tr key={user.id} className="text-gray-300 hover:bg-gray-800/40">
                <td className="px-5 py-4"><p className="font-medium text-gray-200">{user.display_name || '未命名'}</p><p className="mt-1 text-xs text-gray-500">{user.email || user.id}</p></td>
                <td className="px-4 py-4"><span className={`rounded-full px-2.5 py-1 text-xs ${user.status === 'active' ? 'bg-emerald-900/40 text-emerald-300' : user.status === 'suspended' ? 'bg-red-900/40 text-red-300' : 'bg-amber-900/40 text-amber-300'}`}>{statusLabel[user.status] || user.status}</span><p className="mt-2 text-xs text-gray-600">{user.email_verified ? '邮箱已验证' : '邮箱未验证'}</p></td>
                <td className="px-4 py-4"><select disabled={disabled} value={user.role} onChange={(e) => void mutate(user, { role: e.target.value })} className="rounded-lg border border-gray-700 bg-gray-900 px-2.5 py-2 text-xs disabled:opacity-40"><option value="user">普通用户</option><option value="admin">管理员</option></select></td>
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

      <section className="rounded-2xl border border-gray-800 bg-gray-800/30 p-5">
        <h3 className="font-medium text-gray-200">最近管理操作</h3>
        <div className="mt-4 space-y-2">{logs.slice(0, 12).map((log) => <div key={log.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-gray-900/50 px-4 py-3 text-xs text-gray-500"><span><strong className="font-medium text-gray-300">{log.actor_email || '系统'}</strong> · {log.action} · {log.target_email || '-'}</span><span>{new Date(log.created_at).toLocaleString()}</span></div>)}{logs.length === 0 && <p className="py-4 text-sm text-gray-600">暂无审计记录</p>}</div>
      </section>
    </div>
  )
}

