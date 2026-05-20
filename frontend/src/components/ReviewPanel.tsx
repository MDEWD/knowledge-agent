import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { fetchReviews, generateReview, streamReviewChat } from '../api/client'
import type { Review } from '../types'

const DAY_OPTIONS = [7, 14, 30]

// Next Monday 09:00 for display
function nextMondayStr() {
  const now = new Date()
  const day = now.getDay()
  const daysUntilMon = day === 1 ? 7 : (8 - day) % 7
  const next = new Date(now)
  next.setDate(now.getDate() + daysUntilMon)
  next.setHours(9, 0, 0, 0)
  return next.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', weekday: 'short' }) + ' 09:00'
}

export default function ReviewPanel() {
  const [reviews, setReviews] = useState<Review[]>([])
  const [selected, setSelected] = useState<Review | null>(null)
  const [generating, setGenerating] = useState(false)
  const [days, setDays] = useState(7)
  const [error, setError] = useState('')

  useEffect(() => {
    fetchReviews().then(setReviews).catch(console.error)
  }, [])

  const handleGenerate = async () => {
    setGenerating(true)
    setError('')
    try {
      const result = await generateReview(days)
      if (!result.report) {
        setError(`过去 ${days} 天内没有新增视频，无法生成复盘报告。`)
        return
      }
      const newReview: Review = {
        filename: `${result.date} 周复盘（${result.video_count}个视频）.md`,
        date: result.date,
        video_count: result.video_count,
        preview: result.report.slice(0, 200),
        content: result.report,
      }
      setReviews((prev) => [newReview, ...prev.filter((r) => r.date !== result.date)])
      setSelected(newReview)
    } catch (err) {
      setError(String(err))
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="flex h-full gap-4 min-h-0">
      {/* Left: controls + list */}
      <div className="w-56 shrink-0 flex flex-col gap-3">
        <div className="bg-gray-800 rounded-xl p-4 space-y-3">
          <p className="text-sm font-medium text-white">生成复盘报告</p>
          <div className="flex gap-1">
            {DAY_OPTIONS.map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  days === d ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                }`}
              >
                {d}天
              </button>
            ))}
          </div>
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="w-full py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700
              disabled:text-gray-500 text-white text-sm rounded-lg transition-colors
              flex items-center justify-center gap-2"
          >
            {generating ? (
              <>
                <span className="inline-block w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                生成中…
              </>
            ) : '生成报告'}
          </button>
          {error && <p className="text-xs text-red-400">{error}</p>}
          <div className="pt-1 border-t border-gray-700">
            <p className="text-[10px] text-gray-600">⏰ 下次自动复盘</p>
            <p className="text-[10px] text-gray-500 mt-0.5">{nextMondayStr()}</p>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5">
          {reviews.length === 0 ? (
            <p className="text-xs text-gray-600 text-center pt-6">暂无复盘报告</p>
          ) : reviews.map((r) => (
            <button
              key={r.filename}
              onClick={() => setSelected(r)}
              className={`w-full text-left px-3 py-2.5 rounded-xl transition-colors ${
                selected?.filename === r.filename
                  ? 'bg-blue-600/20 border border-blue-500/50'
                  : 'bg-gray-800 border border-transparent hover:border-gray-700'
              }`}
            >
              <p className="text-sm text-gray-200 font-medium">{r.date}</p>
              <p className="text-xs text-gray-500 mt-0.5">{r.video_count} 个视频</p>
            </button>
          ))}
        </div>
      </div>

      {/* Right: report viewer + agent chat */}
      {selected ? (
        <div className="flex-1 min-w-0 flex flex-col gap-3 min-h-0">
          {/* Report */}
          <div className="flex-1 min-h-0 overflow-y-auto bg-gray-800 rounded-xl p-5">
            <div className="flex items-baseline justify-between mb-4 pb-3 border-b border-gray-700">
              <h2 className="text-sm font-semibold text-white">{selected.date} 复盘报告</h2>
              <span className="text-xs text-gray-500">{selected.video_count} 个视频</span>
            </div>
            <div className="prose-custom text-sm">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{selected.content}</ReactMarkdown>
            </div>
          </div>

          {/* Agent chat — key resets chat when review changes */}
          <ReviewChat key={selected.filename} review={selected} />
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center text-gray-600 text-sm">
          {reviews.length > 0 ? '选择左侧报告查看内容' : '点击「生成报告」开始你的第一次知识复盘'}
        </div>
      )}
    </div>
  )
}

// ── Embedded review chat ──────────────────────────────────────────────────────

const QUICK_ACTIONS = [
  '帮我制定下周具体学习计划',
  '展开讲讲报告中最重要的知识点',
  '这期学习有哪些我可以立刻行动的？',
  '我在哪些方向学得还不够深？',
]

let _chatIdCounter = 0
const nextChatId = () => String(++_chatIdCounter)

interface ChatMsg { id: string; role: 'user' | 'assistant'; content: string }

function ReviewChat({ review }: { review: Review }) {
  const [messages, setMessages] = useState<ChatMsg[]>([
    {
      id: nextChatId(),
      role: 'assistant',
      content: `复盘报告已加载（${review.date}，${review.video_count} 个视频）。你可以问我任何关于这份报告的问题，或点击下方快捷提问。`,
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const send = async (text: string) => {
    const t = text.trim()
    if (!t || loading) return

    const userMsg: ChatMsg = { id: nextChatId(), role: 'user', content: t }
    const assistantId = nextChatId()
    const assistantMsg: ChatMsg = { id: assistantId, role: 'assistant', content: '' }

    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setInput('')
    setLoading(true)

    const history = [...messages, userMsg].map(({ role, content }) => ({ role, content }))

    try {
      for await (const event of streamReviewChat(review.content, history)) {
        if (event.type === 'text') {
          setMessages((prev) =>
            prev.map((m) => m.id === assistantId ? { ...m, content: m.content + event.content } : m)
          )
        }
      }
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) => m.id === assistantId ? { ...m, content: `出错了：${String(err)}` } : m)
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-64 shrink-0 bg-gray-800 rounded-xl flex flex-col border border-gray-700/50">
      {/* Chat header */}
      <div className="px-4 py-2.5 border-b border-gray-700 flex items-center gap-2 shrink-0">
        <div className="w-5 h-5 rounded-full bg-purple-600 flex items-center justify-center text-[10px] font-bold">
          R
        </div>
        <span className="text-xs font-medium text-gray-300">复盘 Agent</span>
        <span className="text-[10px] text-gray-600 ml-auto">基于当前报告回答</span>
      </div>

      {/* Messages */}
      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-2">
        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] rounded-xl px-3 py-1.5 text-xs ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white rounded-br-sm'
                  : 'bg-gray-700 text-gray-200 rounded-bl-sm'
              }`}
            >
              {msg.role === 'assistant' ? (
                <div className="prose-custom prose-xs">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.content || (loading ? '▌' : '')}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Quick actions — only show when idle and few messages */}
      {!loading && messages.length <= 2 && (
        <div className="px-3 pb-2 flex flex-wrap gap-1.5 shrink-0">
          {QUICK_ACTIONS.map((q) => (
            <button
              key={q}
              onClick={() => send(q)}
              className="text-[10px] px-2.5 py-1 bg-gray-700 hover:bg-purple-700/50 hover:text-purple-200
                text-gray-400 rounded-full transition-colors border border-gray-600 hover:border-purple-500"
            >
              {q}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="px-3 pb-3 shrink-0">
        <div className="flex gap-2 items-center">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
            placeholder="问问复盘 Agent…"
            disabled={loading}
            className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-3 py-1.5 text-xs text-white
              placeholder-gray-500 focus:outline-none focus:border-purple-500 disabled:opacity-50"
          />
          <button
            onClick={() => send(input)}
            disabled={loading || !input.trim()}
            className="px-3 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700
              disabled:text-gray-500 text-white text-xs rounded-lg transition-colors shrink-0"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  )
}
