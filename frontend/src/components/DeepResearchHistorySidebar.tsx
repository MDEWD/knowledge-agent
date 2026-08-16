import { useEffect, useState } from 'react'
import {
  deleteDeepResearchSession,
  fetchDeepResearchHistory,
} from '../api/client'
import type { DeepResearchSessionSummary } from '../api/client'

interface Props {
  activeSessionId: string | null
  refreshKey: number
  disabled?: boolean
  onSelect: (sessionId: string) => void
  onNew: () => void
}

function formatUpdatedAt(value: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

export default function DeepResearchHistorySidebar({
  activeSessionId,
  refreshKey,
  disabled = false,
  onSelect,
  onNew,
}: Props) {
  const [sessions, setSessions] = useState<DeepResearchSessionSummary[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchDeepResearchHistory()
      .then((items) => {
        if (!cancelled) setSessions(items)
      })
      .catch(() => {
        if (!cancelled) setSessions([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [refreshKey])

  const handleDelete = async (sessionId: string, event: React.MouseEvent) => {
    event.stopPropagation()
    await deleteDeepResearchSession(sessionId)
    setSessions((items) => items.filter((item) => item.id !== sessionId))
    if (activeSessionId === sessionId) onNew()
  }

  return (
    <aside className="flex w-72 shrink-0 flex-col border-r border-gray-800 p-4">
      <button
        onClick={onNew}
        disabled={disabled}
        className="mb-4 flex w-full items-center justify-center gap-2 rounded-lg bg-cyan-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <span className="text-base leading-none">＋</span>
        新建研究
      </button>

      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-300">研究历史</h2>
        <span className="text-xs text-gray-500">{sessions.length}</span>
      </div>

      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
        {loading && <p className="py-6 text-center text-xs text-gray-600">加载中…</p>}
        {!loading && sessions.length === 0 && (
          <p className="py-6 text-center text-xs text-gray-600">暂无研究记录</p>
        )}
        {sessions.map((session) => (
          <div
            key={session.id}
            role="button"
            tabIndex={disabled ? -1 : 0}
            aria-disabled={disabled}
            onClick={() => !disabled && onSelect(session.id)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                if (!disabled) onSelect(session.id)
              }
            }}
            className={`group flex w-full items-start gap-2 rounded-lg border px-3 py-2.5 text-left transition-colors ${
              activeSessionId === session.id
                ? 'border-cyan-800 bg-cyan-950/30'
                : 'border-transparent hover:border-gray-700 hover:bg-gray-800'
            }`}
          >
            <span className="mt-0.5 text-sm">📄</span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs font-medium text-gray-300" title={session.title}>
                {session.title}
              </span>
              <span className="mt-1 block text-[10px] text-gray-500">
                {formatUpdatedAt(session.updated_at)} · {session.turn_count} 轮
              </span>
            </span>
            <button
              type="button"
              disabled={disabled}
              title="删除记录"
              onClick={(event) => void handleDelete(session.id, event)}
              className="opacity-0 text-xs text-gray-600 transition-opacity hover:text-red-400 group-hover:opacity-100"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </aside>
  )
}
