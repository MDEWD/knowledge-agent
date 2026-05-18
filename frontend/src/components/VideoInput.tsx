import { useEffect, useState } from 'react'
import { checkDuplicate, submitVideo, watchTask } from '../api/client'
import type { ProcessingEvent, Video } from '../types'

interface Props {
  onDone: (video: Video) => void
  prefillUrl?: string
  onClearPrefill?: () => void
}

const PLATFORMS = [
  {
    id: 'youtube',
    label: 'YouTube',
    icon: '▶',
    placeholder: 'https://www.youtube.com/watch?v=...',
    color: 'border-red-600 bg-red-600/10 text-red-400',
    activeColor: 'border-red-500 bg-red-500/20 text-red-300',
  },
  {
    id: 'bilibili',
    label: 'Bilibili',
    icon: '📺',
    placeholder: 'https://www.bilibili.com/video/BV...',
    color: 'border-pink-600 bg-pink-600/10 text-pink-400',
    activeColor: 'border-pink-500 bg-pink-500/20 text-pink-300',
  },
  {
    id: 'generic',
    label: '其他平台',
    icon: '🎬',
    placeholder: '粘贴视频链接（支持 Twitter/X、Vimeo、TikTok 等）',
    color: 'border-gray-600 bg-gray-700/30 text-gray-400',
    activeColor: 'border-blue-500 bg-blue-500/10 text-blue-300',
  },
]

const STEP_LABELS: Record<string, string> = {
  extracting: '提取字幕',
  processing: '提炼观点',
  saving: '写入存储',
  done: '完成',
  error: '出错',
  ping: '处理中',
}

export default function VideoInput({ onDone, prefillUrl, onClearPrefill }: Props) {
  const [platform, setPlatform] = useState<string | null>(null)
  const [url, setUrl] = useState('')
  const [event, setEvent] = useState<ProcessingEvent | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [dupVideo, setDupVideo] = useState<Video | null>(null)

  // Auto-fill from recommendation panel
  useEffect(() => {
    if (!prefillUrl) return
    const detected = prefillUrl.includes('youtube.com') || prefillUrl.includes('youtu.be')
      ? 'youtube'
      : prefillUrl.includes('bilibili.com')
      ? 'bilibili'
      : 'generic'
    setPlatform(detected)
    setUrl(prefillUrl)
    setError('')
    setDupVideo(null)
    onClearPrefill?.()
  }, [prefillUrl])

  const selectedPlatform = PLATFORMS.find((p) => p.id === platform)

  const startProcessing = async (targetUrl: string, targetPlatform: string) => {
    setDupVideo(null)
    setError('')
    setLoading(true)
    setEvent({ step: 'extracting', progress: 0, message: '提交中…' })
    try {
      const taskId = await submitVideo(targetUrl, targetPlatform)
      const stop = watchTask(taskId, (ev) => {
        setEvent(ev)
        if (ev.step === 'done' && ev.video) {
          onDone(ev.video)
          setUrl('')
          setLoading(false)
          stop()
        }
        if (ev.step === 'error') {
          setError(ev.message)
          setLoading(false)
          stop()
        }
      })
    } catch (err) {
      setError(String(err))
      setLoading(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim() || !platform) return
    const { duplicate, video } = await checkDuplicate(url.trim())
    if (duplicate && video) {
      setDupVideo(video)
      return
    }
    await startProcessing(url.trim(), platform)
  }

  const handleReset = () => {
    if (loading) return
    setPlatform(null)
    setUrl('')
    setEvent(null)
    setError('')
    setDupVideo(null)
  }

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="text-lg font-semibold text-white mb-1">添加视频到知识库</h2>
        <p className="text-sm text-gray-400">选择平台，再贴入链接</p>
      </div>

      {/* Step 1: Platform selector */}
      <div>
        <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">第一步 · 选择平台</p>
        <div className="flex gap-2">
          {PLATFORMS.map((p) => {
            const isActive = platform === p.id
            return (
              <button
                key={p.id}
                type="button"
                disabled={loading}
                onClick={() => { setPlatform(p.id); setUrl(''); setError(''); setDupVideo(null) }}
                className={`flex-1 flex flex-col items-center gap-1 py-3 px-2 rounded-xl border-2
                  transition-all text-sm font-medium disabled:opacity-50
                  ${isActive ? p.activeColor + ' scale-[1.03]' : p.color + ' hover:border-gray-500'}`}
              >
                <span className="text-xl">{p.icon}</span>
                <span>{p.label}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Step 2: URL input */}
      {platform && (
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <p className="text-xs text-gray-500 uppercase tracking-wide">
            第二步 · 粘贴 {selectedPlatform?.label} 链接
          </p>
          <div className="flex gap-2">
            <input
              type="url"
              value={url}
              onChange={(e) => { setUrl(e.target.value); setDupVideo(null) }}
              placeholder={selectedPlatform?.placeholder}
              disabled={loading}
              autoFocus
              className="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-4 py-2.5 text-sm text-white
                placeholder-gray-500 focus:outline-none focus:border-blue-500 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={loading || !url.trim()}
              className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700
                disabled:text-gray-500 text-white text-sm font-medium rounded-lg transition-colors whitespace-nowrap"
            >
              {loading ? '处理中…' : '添加'}
            </button>
            {!loading && (
              <button
                type="button"
                onClick={handleReset}
                className="px-3 py-2.5 bg-gray-700 hover:bg-gray-600 text-gray-400
                  text-sm rounded-lg transition-colors"
                title="重新选择平台"
              >
                ↩
              </button>
            )}
          </div>
        </form>
      )}

      {/* Duplicate warning */}
      {dupVideo && (
        <div className="bg-yellow-900/30 border border-yellow-700 rounded-lg p-4">
          <p className="text-sm font-medium text-yellow-300 mb-1">该视频已在知识库中</p>
          <p className="text-xs text-yellow-500 mb-3 truncate">「{dupVideo.title}」</p>
          <div className="flex gap-2">
            <button
              onClick={() => startProcessing(url.trim(), platform!)}
              className="px-3 py-1.5 text-xs bg-yellow-700 hover:bg-yellow-600 text-white rounded-lg"
            >
              重新处理并覆盖
            </button>
            <button
              onClick={() => setDupVideo(null)}
              className="px-3 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* Progress */}
      {event && event.step !== 'ping' && !dupVideo && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="flex justify-between items-center mb-2">
            <span className="text-sm font-medium text-gray-300">
              {STEP_LABELS[event.step] ?? event.step}
            </span>
            <span className="text-xs text-gray-500">{event.progress}%</span>
          </div>
          <div className="w-full bg-gray-700 rounded-full h-1.5 mb-2">
            <div
              className={`h-1.5 rounded-full transition-all duration-500 ${
                event.step === 'error' ? 'bg-red-500' : 'bg-blue-500'
              }`}
              style={{ width: `${event.progress}%` }}
            />
          </div>
          <p className="text-xs text-gray-400">{event.message}</p>
          {event.step === 'done' && event.video && (
            <div className="mt-3 pt-3 border-t border-gray-700">
              <p className="text-sm text-green-400 font-medium">已保存到知识库 ✓</p>
              <p className="text-xs text-gray-400 mt-1 truncate">{event.video.title}</p>
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-900/30 border border-red-700 rounded-lg p-3">
          <p className="text-sm text-red-400">{error}</p>
        </div>
      )}
    </div>
  )
}
