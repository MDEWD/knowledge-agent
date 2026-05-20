import { useState } from 'react'
import { fetchRecommendations } from '../api/client'
import type { Recommendation, YoutubeVideoSuggestion } from '../types'

interface Props {
  hasVideos: boolean
  onAddVideo: (url: string) => void
}

export default function RecommendationsPanel({ hasVideos, onAddVideo }: Props) {
  const [recs, setRecs] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')

  const handleAnalyze = async () => {
    setLoading(true)
    setError('')
    setDone(false)
    try {
      const data = await fetchRecommendations()
      setRecs(data)
      setDone(true)
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="border border-gray-700 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-gray-800/60">
        <div className="flex items-center gap-2">
          <span className="text-base">🧭</span>
          <div>
            <p className="text-sm font-medium text-white">主动学习推荐</p>
            <p className="text-xs text-gray-500">基于你的知识库，发现学习盲点</p>
          </div>
        </div>
        <button
          onClick={handleAnalyze}
          disabled={loading || !hasVideos}
          title={!hasVideos ? '先添加一些视频再分析' : undefined}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500
            disabled:bg-gray-700 disabled:text-gray-500 text-white text-xs font-medium
            rounded-lg transition-colors shrink-0"
        >
          {loading ? (
            <>
              <span className="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
              分析中…
            </>
          ) : done ? (
            '重新分析'
          ) : (
            '分析并推荐'
          )}
        </button>
      </div>

      {/* Content */}
      {!hasVideos && !done && (
        <div className="px-4 py-5 text-center text-xs text-gray-600">
          先添加一些视频到知识库，才能生成个性化推荐
        </div>
      )}

      {hasVideos && !done && !loading && !error && (
        <div className="px-4 py-5 text-center text-xs text-gray-600">
          点击「分析并推荐」，Agent 将分析你的知识库并推荐相关学习内容
        </div>
      )}

      {error && (
        <div className="px-4 py-3">
          <p className="text-xs text-red-400">{error}</p>
        </div>
      )}

      {done && recs.length === 0 && (
        <div className="px-4 py-5 text-center text-xs text-gray-500">
          暂时没有找到推荐，知识库内容可能还不够丰富
        </div>
      )}

      {recs.length > 0 && (
        <div className="divide-y divide-gray-800">
          {recs.map((rec, i) => (
            <TopicSection key={i} rec={rec} onAddVideo={onAddVideo} />
          ))}
        </div>
      )}
    </div>
  )
}

function TopicSection({ rec, onAddVideo }: { rec: Recommendation; onAddVideo: (url: string) => void }) {
  return (
    <div className="px-4 py-3 space-y-2">
      <div>
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-blue-300 bg-blue-900/30 border border-blue-800/50 rounded-full px-2.5 py-0.5">
          {rec.topic}
        </span>
        <p className="text-xs text-gray-500 mt-1">{rec.reason}</p>
      </div>
      <div className="space-y-1.5">
        {rec.videos.length === 0 ? (
          <p className="text-xs text-gray-600 italic">暂无搜索结果</p>
        ) : (
          rec.videos.map((v, i) => (
            <VideoRow key={i} video={v} onAdd={() => onAddVideo(v.url)} />
          ))
        )}
      </div>
    </div>
  )
}

function VideoRow({ video, onAdd }: { video: YoutubeVideoSuggestion; onAdd: () => void }) {
  const mins = video.duration ? Math.round(video.duration / 60) : null
  return (
    <div className="flex items-center gap-2 group">
      <a
        href={video.url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-2.5 flex-1 min-w-0 bg-gray-800/50 hover:bg-gray-800
          border border-gray-700/50 hover:border-gray-600 rounded-lg px-3 py-2 transition-colors"
      >
        <div className="w-6 h-6 rounded bg-red-600 flex items-center justify-center shrink-0">
          <svg className="w-3 h-3 text-white" viewBox="0 0 24 24" fill="currentColor">
            <path d="M8 5v14l11-7z" />
          </svg>
        </div>
        <div className="min-w-0">
          <p className="text-xs text-gray-200 truncate">{video.title}</p>
          <p className="text-[10px] text-gray-500">
            {video.channel}{mins ? ` · ${mins} 分钟` : ''}
          </p>
        </div>
      </a>
      <button
        onClick={onAdd}
        className="shrink-0 px-2.5 py-1.5 text-[10px] font-medium bg-gray-700 hover:bg-blue-600
          text-gray-300 hover:text-white rounded-lg transition-colors whitespace-nowrap"
        title="添加到知识库"
      >
        + 添加
      </button>
    </div>
  )
}
