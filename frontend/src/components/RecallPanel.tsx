import { useEffect, useState } from 'react'
import { fetchDueCards, fetchAllCards, generateRecallCards, reviewRecallCard, deleteRecallCards } from '../api/client'
import type { RecallCard, RecallStats, Video } from '../types'

interface Props {
  videos: Video[]
}

const QUALITY_LABELS = [
  { q: 1, label: '完全不会', color: 'bg-red-700 hover:bg-red-600' },
  { q: 2, label: '模糊记得', color: 'bg-orange-700 hover:bg-orange-600' },
  { q: 3, label: '想起来了', color: 'bg-yellow-700 hover:bg-yellow-600' },
  { q: 4, label: '记得清楚', color: 'bg-emerald-700 hover:bg-emerald-600' },
  { q: 5, label: '完全掌握', color: 'bg-green-600 hover:bg-green-500' },
]

export default function RecallPanel({ videos }: Props) {
  const [mode, setMode] = useState<'browse' | 'review'>('browse')
  const [stats, setStats] = useState<RecallStats>({ total: 0, due_today: 0, mastered: 0, learning: 0 })
  const [dueCards, setDueCards] = useState<RecallCard[]>([])
  const [cardsByVideo, setCardsByVideo] = useState<Record<string, number>>({})
  const [generating, setGenerating] = useState<string | null>(null)
  const [currentIdx, setCurrentIdx] = useState(0)
  const [flipped, setFlipped] = useState(false)
  const [sessionDone, setSessionDone] = useState(false)
  const [reviewed, setReviewed] = useState(0)

  const load = async () => {
    const { cards, stats: s } = await fetchAllCards()
    setStats(s)
    const counts: Record<string, number> = {}
    for (const c of cards) counts[c.video_id] = (counts[c.video_id] || 0) + 1
    setCardsByVideo(counts)
    const due = await fetchDueCards()
    setDueCards(due.cards)
  }

  useEffect(() => { load() }, [])

  const handleGenerate = async (videoId: string) => {
    setGenerating(videoId)
    try {
      await generateRecallCards(videoId, 5)
      await load()
    } finally {
      setGenerating(null)
    }
  }

  const handleDelete = async (videoId: string) => {
    await deleteRecallCards(videoId)
    await load()
  }

  const startReview = async () => {
    const { cards } = await fetchDueCards()
    setDueCards(cards)
    setCurrentIdx(0)
    setFlipped(false)
    setSessionDone(false)
    setReviewed(0)
    setMode('review')
  }

  const handleRate = async (quality: number) => {
    const card = dueCards[currentIdx]
    if (!card) return
    await reviewRecallCard(card.id, quality)
    const next = currentIdx + 1
    setReviewed((r) => r + 1)
    if (next >= dueCards.length) {
      setSessionDone(true)
      await load()
    } else {
      setCurrentIdx(next)
      setFlipped(false)
    }
  }

  if (mode === 'review') {
    const card = dueCards[currentIdx]
    const total = dueCards.length

    if (sessionDone || !card) {
      return (
        <div className="h-full flex flex-col items-center justify-center gap-6 text-center">
          <div className="w-16 h-16 rounded-full bg-green-600/20 flex items-center justify-center text-3xl">🎉</div>
          <div>
            <p className="text-xl font-bold text-white">复习完成！</p>
            <p className="text-sm text-gray-400 mt-1">本次复习了 {reviewed} 张卡片</p>
          </div>
          <div className="flex gap-4 text-sm">
            <div className="text-center">
              <p className="text-2xl font-bold text-green-400">{stats.mastered}</p>
              <p className="text-gray-500">已掌握</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-blue-400">{stats.learning}</p>
              <p className="text-gray-500">学习中</p>
            </div>
          </div>
          <button
            onClick={() => setMode('browse')}
            className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-xl"
          >
            返回卡片库
          </button>
        </div>
      )
    }

    return (
      <div className="h-full flex flex-col gap-4">
        {/* Progress */}
        <div className="flex items-center justify-between">
          <button onClick={() => setMode('browse')} className="text-xs text-gray-500 hover:text-gray-300">← 退出</button>
          <span className="text-xs text-gray-500">{currentIdx + 1} / {total}</span>
          <span className="text-xs text-gray-600 truncate max-w-[180px]">{card.video_title}</span>
        </div>
        <div className="w-full h-1 bg-gray-800 rounded-full">
          <div className="h-1 bg-blue-500 rounded-full transition-all" style={{ width: `${(currentIdx / total) * 100}%` }} />
        </div>

        {/* Card */}
        <div
          onClick={() => !flipped && setFlipped(true)}
          className={`flex-1 rounded-2xl border-2 flex flex-col items-center justify-center p-8 cursor-pointer
            transition-all duration-300 select-none ${
              flipped
                ? 'border-blue-500 bg-blue-900/10'
                : 'border-gray-700 bg-gray-800/50 hover:border-gray-600'
            }`}
        >
          {!flipped ? (
            <div className="text-center">
              <p className="text-xs text-gray-500 uppercase tracking-widest mb-6">问题</p>
              <p className="text-lg text-white font-medium leading-relaxed">{card.question}</p>
              <p className="text-xs text-gray-600 mt-8">点击翻转查看答案</p>
            </div>
          ) : (
            <div className="text-center w-full">
              <p className="text-xs text-gray-500 uppercase tracking-widest mb-4">问题</p>
              <p className="text-sm text-gray-400 mb-6 leading-relaxed">{card.question}</p>
              <div className="w-full h-px bg-gray-700 mb-6" />
              <p className="text-xs text-blue-400 uppercase tracking-widest mb-4">答案</p>
              <p className="text-base text-white leading-relaxed">{card.answer}</p>
            </div>
          )}
        </div>

        {/* Rating buttons */}
        {flipped && (
          <div>
            <p className="text-xs text-gray-500 text-center mb-2">你记得多好？</p>
            <div className="flex gap-2">
              {QUALITY_LABELS.map(({ q, label, color }) => (
                <button
                  key={q}
                  onClick={() => handleRate(q)}
                  className={`flex-1 py-2.5 rounded-xl text-xs font-medium text-white transition-colors ${color}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }

  // Browse mode
  return (
    <div className="h-full flex flex-col gap-5">
      {/* Stats header */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: '总卡片', value: stats.total, color: 'text-white' },
          { label: '今日待复', value: stats.due_today, color: stats.due_today > 0 ? 'text-amber-400' : 'text-white' },
          { label: '学习中', value: stats.learning, color: 'text-blue-400' },
          { label: '已掌握', value: stats.mastered, color: 'text-green-400' },
        ].map((s) => (
          <div key={s.label} className="bg-gray-800 rounded-xl p-3 text-center border border-gray-700">
            <p className={`text-xl font-bold ${s.color}`}>{s.value}</p>
            <p className="text-xs text-gray-500 mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Start review button */}
      {stats.due_today > 0 && (
        <button
          onClick={startReview}
          className="flex items-center justify-center gap-2 py-3 bg-blue-600 hover:bg-blue-500
            text-white text-sm font-medium rounded-xl transition-colors"
        >
          <span>▶</span>
          <span>开始今日复习（{stats.due_today} 张）</span>
        </button>
      )}

      {/* Video card list */}
      <div className="flex-1 overflow-y-auto space-y-2 min-h-0">
        <p className="text-xs text-gray-500 uppercase tracking-wide">视频卡片库</p>
        {videos.length === 0 && (
          <p className="text-sm text-gray-500 py-4">请先添加视频到知识库</p>
        )}
        {videos.map((v) => {
          const count = cardsByVideo[v.id] || 0
          const isGenerating = generating === v.id
          return (
            <div key={v.id} className="flex items-center gap-3 bg-gray-800 rounded-xl px-4 py-3 border border-gray-700">
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white truncate">{v.title}</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  {count > 0 ? `${count} 张卡片` : '暂无卡片'}
                </p>
              </div>
              <div className="flex gap-1.5 shrink-0">
                <button
                  onClick={() => handleGenerate(v.id)}
                  disabled={isGenerating}
                  className="px-3 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300
                    rounded-lg transition-colors disabled:opacity-50"
                >
                  {isGenerating ? '生成中…' : count > 0 ? '重新生成' : '生成卡片'}
                </button>
                {count > 0 && (
                  <button
                    onClick={() => handleDelete(v.id)}
                    className="px-2 py-1.5 text-xs bg-gray-700 hover:bg-red-900/50 text-gray-500
                      hover:text-red-400 rounded-lg transition-colors"
                    title="删除该视频的所有卡片"
                  >
                    ✕
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
