import { useEffect, useState } from 'react'
import { fetchMemory, updateMemory, resetMemory } from '../api/client'
import type { UserMemory } from '../types'

interface Props {
  defaultOpen?: boolean
  hideToggle?: boolean
  className?: string
}

export default function MemorySidebar({ defaultOpen = false, hideToggle = false, className = '' }: Props) {
  const [mem, setMem] = useState<UserMemory | null>(null)
  const [open, setOpen] = useState(defaultOpen)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')

  useEffect(() => {
    fetchMemory().then(setMem).catch(() => {})
  }, [])

  const hasMem = mem && (mem.summary || mem.interests.length > 0 || mem.learning_goals.length > 0)

  const handleSave = async () => {
    if (!mem) return
    const updated = await updateMemory({ ...mem, summary: draft })
    setMem(updated)
    setEditing(false)
  }

  const handleReset = async () => {
    if (!confirm('确认清除所有长期记忆？')) return
    const reset = await resetMemory()
    setMem(reset)
  }

  return (
    <div className={`${hideToggle ? '' : 'border-t border-gray-800 mt-3 pt-3'} ${className}`}>
      {!hideToggle && (
        <button
          onClick={() => setOpen((o) => !o)}
          className="w-full flex items-center justify-between text-xs text-gray-500 hover:text-gray-300 transition-colors py-1"
        >
          <span className="flex items-center gap-1.5">
            <span className={`w-1.5 h-1.5 rounded-full ${hasMem ? 'bg-purple-400' : 'bg-gray-600'}`} />
            长期记忆
          </span>
          <span>{open ? '▲' : '▼'}</span>
        </button>
      )}

      {(open || hideToggle) && (
        <div className="mt-2 space-y-2">
          {!hasMem ? (
            <p className="text-xs text-gray-600 py-1">对话后自动积累用户画像</p>
          ) : (
            <>
              {mem?.summary && (
                <div>
                  {editing ? (
                    <div className="space-y-1">
                      <textarea
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        rows={2}
                        className="w-full bg-gray-800 border border-gray-600 rounded-lg px-2 py-1.5 text-xs text-white
                          focus:outline-none focus:border-purple-500 resize-none"
                      />
                      <div className="flex gap-1">
                        <button onClick={handleSave} className="text-xs px-2 py-1 bg-purple-700 hover:bg-purple-600 text-white rounded">保存</button>
                        <button onClick={() => setEditing(false)} className="text-xs px-2 py-1 bg-gray-700 text-gray-400 rounded">取消</button>
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => { setDraft(mem.summary); setEditing(true) }}
                      className="text-left text-xs text-gray-400 hover:text-gray-200 leading-relaxed w-full"
                    >
                      {mem.summary}
                    </button>
                  )}
                </div>
              )}

              {mem && mem.interests.length > 0 && (
                <div>
                  <p className="text-[10px] text-gray-600 uppercase tracking-wide mb-1">兴趣</p>
                  <div className="flex flex-wrap gap-1">
                    {mem.interests.slice(0, 6).map((t) => (
                      <span key={t} className="px-1.5 py-0.5 bg-purple-900/40 text-purple-300 rounded text-[10px]">{t}</span>
                    ))}
                  </div>
                </div>
              )}

              {mem && mem.learning_goals.length > 0 && (
                <div>
                  <p className="text-[10px] text-gray-600 uppercase tracking-wide mb-1">目标</p>
                  {mem.learning_goals.slice(0, 3).map((g) => (
                    <p key={g} className="text-[10px] text-gray-500 flex items-start gap-1">
                      <span className="text-purple-500 shrink-0">›</span>{g}
                    </p>
                  ))}
                </div>
              )}

              {mem && mem.gaps.length > 0 && (
                <div>
                  <p className="text-[10px] text-gray-600 uppercase tracking-wide mb-1">盲点</p>
                  {mem.gaps.slice(0, 3).map((g) => (
                    <p key={g} className="text-[10px] text-amber-600 flex items-start gap-1">
                      <span className="shrink-0">?</span>{g}
                    </p>
                  ))}
                </div>
              )}
            </>
          )}

          <button
            onClick={handleReset}
            className="text-[10px] text-gray-700 hover:text-red-500 transition-colors mt-1"
          >
            清除记忆
          </button>
        </div>
      )}
    </div>
  )
}
