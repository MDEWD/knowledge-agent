import { useEffect } from 'react'
import MemorySidebar from './MemorySidebar'

interface Props {
  open: boolean
  onClose: () => void
}

export default function GlobalMemoryDrawer({ open, onClose }: Props) {
  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50">
      <button
        type="button"
        aria-label="关闭长期记忆"
        onClick={onClose}
        className="absolute inset-0 bg-black/40 backdrop-blur-[1px]"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="global-memory-title"
        className="absolute inset-y-0 right-0 flex w-full max-w-sm flex-col border-l border-gray-800 bg-gray-900 shadow-2xl"
      >
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-800 px-5">
          <div>
            <h2 id="global-memory-title" className="text-sm font-semibold text-white">长期记忆</h2>
            <p className="text-[10px] text-gray-500">跨笔记、对话与深度研究共享</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-gray-500 transition-colors hover:bg-gray-800 hover:text-white"
            aria-label="关闭"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <MemorySidebar defaultOpen hideToggle />
        </div>
      </aside>
    </div>
  )
}
