import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getNote, updateNote } from '../api/client'
import type { Video } from '../types'

interface Props {
  video: Video
  allVideos: Video[]
  onSelectVideo: (v: Video) => void
}

export default function NoteEditor({ video, allVideos, onSelectVideo }: Props) {
  const [insights, setInsights] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [preview, setPreview] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    getNote(video.id)
      .then(({ insights }) => setInsights(insights))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [video.id])

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      await updateNote(video.id, insights)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  const relatedVideos = (video.related_ids ?? [])
    .map((id) => allVideos.find((v) => v.id === id))
    .filter(Boolean) as Video[]

  if (loading) {
    return <div className="h-full flex items-center justify-center text-gray-500 text-sm">加载中…</div>
  }

  return (
    <div className="h-full flex flex-col gap-3">
      {/* Toolbar */}
      <div className="flex items-center justify-between shrink-0">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-white truncate">{video.title}</h2>
          {video.category && <span className="text-xs text-blue-400">{video.category}</span>}
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-3">
          <button
            onClick={() => setPreview((p) => !p)}
            className="px-3 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg transition-colors"
          >
            {preview ? '编辑' : '预览'}
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${
              saved
                ? 'bg-green-700 text-white'
                : 'bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white'
            }`}
          >
            {saving ? '保存中…' : saved ? '已保存 ✓' : '保存'}
          </button>
        </div>
      </div>

      {/* Editor / Preview */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {preview ? (
          <div className="bg-gray-800 rounded-lg p-5 border border-gray-700
            prose prose-invert prose-sm max-w-none
            prose-headings:text-gray-100 prose-p:text-gray-300 prose-li:text-gray-300
            prose-code:text-blue-300 prose-code:bg-gray-700 prose-code:px-1 prose-code:rounded">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{insights}</ReactMarkdown>
          </div>
        ) : (
          <textarea
            value={insights}
            onChange={(e) => setInsights(e.target.value)}
            className="w-full h-full bg-gray-800 border border-gray-700 rounded-lg p-4 text-sm text-gray-200
              font-mono resize-none focus:outline-none focus:border-blue-500 leading-relaxed"
            placeholder="笔记内容…"
            spellCheck={false}
          />
        )}
      </div>

      {error && <p className="shrink-0 text-xs text-red-400">{error}</p>}

      {/* Related videos */}
      {relatedVideos.length > 0 && (
        <div className="shrink-0 border-t border-gray-800 pt-3">
          <p className="text-xs text-gray-500 mb-2">相关笔记</p>
          <div className="flex flex-col gap-1">
            {relatedVideos.map((v) => (
              <button
                key={v.id}
                onClick={() => onSelectVideo(v)}
                className="text-left text-xs text-blue-400 hover:text-blue-300 truncate transition-colors"
              >
                → {v.title}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
