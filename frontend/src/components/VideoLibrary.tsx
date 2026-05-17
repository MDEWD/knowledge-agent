import { useState } from 'react'
import { deleteVideo } from '../api/client'
import type { Video } from '../types'

interface Props {
  videos: Video[]
  onDelete: (id: string) => void
  onSelectVideo?: (video: Video) => void
}

const PLATFORM_ICON: Record<string, string> = {
  youtube: '▶',
  bilibili: '📺',
}

function formatDuration(seconds?: number): string {
  if (!seconds) return ''
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('zh-CN', {
    month: 'short',
    day: 'numeric',
  })
}

export default function VideoLibrary({ videos, onDelete, onSelectVideo }: Props) {
  const [search, setSearch] = useState('')
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const filtered = videos.filter(
    (v) =>
      v.title.toLowerCase().includes(search.toLowerCase()) ||
      v.channel.toLowerCase().includes(search.toLowerCase()) ||
      v.tags.some((t) => t.toLowerCase().includes(search.toLowerCase())),
  )

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('确定要从知识库中删除这个视频吗？')) return
    setDeletingId(id)
    try {
      await deleteVideo(id)
      onDelete(id)
    } catch (err) {
      alert(String(err))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="flex flex-col h-full gap-3">
      <div>
        <h2 className="text-sm font-semibold text-gray-300 mb-2">
          知识库 <span className="text-gray-500 font-normal">({videos.length})</span>
        </h2>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索标题、频道、标签…"
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs
            text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
        />
      </div>

      <div className="flex-1 overflow-y-auto space-y-1 min-h-0">
        {filtered.length === 0 && (
          <div className="text-center py-10 text-gray-600 text-sm">
            {videos.length === 0 ? '还没有视频，去添加第一个吧' : '无匹配结果'}
          </div>
        )}

        {filtered.map((video) => (
          <div
            key={video.id}
            onClick={() => onSelectVideo?.(video)}
            className="group flex items-start gap-2.5 p-2.5 rounded-lg hover:bg-gray-800
              cursor-pointer transition-colors border border-transparent hover:border-gray-700"
          >
            <span className="text-base mt-0.5 shrink-0">
              {PLATFORM_ICON[video.platform] ?? '🎬'}
            </span>

            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-gray-200 truncate leading-tight">
                {video.title}
              </p>
              <p className="text-xs text-gray-500 mt-0.5 truncate">
                {video.channel}
                {video.duration ? ` · ${formatDuration(video.duration)}` : ''}
                {' · '}{formatDate(video.created_at)}
              </p>
              {video.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {video.tags.slice(0, 3).map((tag) => (
                    <span
                      key={tag}
                      className="text-[10px] bg-gray-700 text-gray-400 px-1.5 py-0.5 rounded"
                    >
                      #{tag}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <button
              onClick={(e) => handleDelete(video.id, e)}
              disabled={deletingId === video.id}
              className="shrink-0 opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400
                text-xs transition-opacity p-0.5"
              title="删除"
            >
              {deletingId === video.id ? '…' : '✕'}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
