import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { streamChat, fetchVideos, fetchStats } from '../api/client'
import type { ChatMessage, CitationSource, Stats, ToolCallRecord, Video, YoutubeVideoSuggestion } from '../types'

let _idCounter = 0
const nextId = () => String(++_idCounter)

const STORAGE_KEY = 'chat_messages'
const MODEL_STORAGE_KEY = 'chat_model'

const MODELS = [
  { id: 'deepseek', icon: '⚡', label: 'DeepSeek' },
  { id: 'qwen',     icon: '🌙', label: '千问' },
]
const WELCOME: ChatMessage = {
  id: '0',
  role: 'assistant',
  content: '你好！我是你的知识库助手，支持多种工具来帮你探索知识库。你可以问我：\n\n- 最近学了哪些视频？\n- 对比几个视频的核心观点\n- 某分类下有哪些内容？\n- 帮我生成一篇关于「XX主题」的综合文章',
}

function loadMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as ChatMessage[]
      if (parsed.length > 0) return parsed
    }
  } catch { /* ignore */ }
  return [WELCOME]
}

function buildSuggestions(videos: Video[], stats: Stats | null): string[] {
  const s: string[] = []
  if (videos.length > 0) {
    s.push(`帮我总结《${videos[0].title.slice(0, 18)}》的核心内容`)
  }
  if (stats) {
    const topCat = Object.entries(stats.categories).sort((a, b) => b[1] - a[1])[0]
    if (topCat) s.push(`「${topCat[0]}」类别下有哪些值得关注的内容？`)
    if (stats.top_tags.length > 0) s.push(`帮我梳理「${stats.top_tags[0].tag}」相关的所有知识点`)
  }
  if (videos.length >= 3) {
    s.push('对比最近几个视频的核心观点，找出共同规律')
  } else {
    s.push('我的知识库里有哪些内容？')
  }
  if (s.length < 2) s.push('列出知识库中最有价值的洞见')
  return s.slice(0, 4)
}

interface Props {
  suggestedVideo?: Video | null
}

export default function ChatInterface({ suggestedVideo }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>(loadMessages)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [toolActivity, setToolActivity] = useState('')
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [expandedCalls, setExpandedCalls] = useState<Set<string>>(new Set())
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [modelId, setModelId] = useState<string>(
    () => localStorage.getItem(MODEL_STORAGE_KEY) ?? 'deepseek'
  )
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const toolCallsRef = useRef<ToolCallRecord[]>([])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, toolActivity])

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(messages)) } catch { /* ignore */ }
  }, [messages])

  useEffect(() => {
    if (suggestedVideo) {
      setInput(`告诉我关于《${suggestedVideo.title}》的核心内容`)
      textareaRef.current?.focus()
    }
  }, [suggestedVideo])

  useEffect(() => {
    Promise.all([fetchVideos(), fetchStats()])
      .then(([vids, stats]) => setSuggestions(buildSuggestions(vids, stats)))
      .catch(() => {})
  }, [])

  // ── Core send logic ──────────────────────────────────────────────────────────

  const handleSend = async (text: string, baseMessages: ChatMessage[]) => {
    if (!text || loading) return

    const userMsg: ChatMessage = { id: nextId(), role: 'user', content: text }
    const assistantId = nextId()
    const assistantMsg: ChatMessage = { id: assistantId, role: 'assistant', content: '' }

    setMessages([...baseMessages, userMsg, assistantMsg])
    setLoading(true)
    setToolActivity('')
    toolCallsRef.current = []

    const history = [...baseMessages, userMsg].map(({ role, content }) => ({ role, content }))

    try {
      for await (const event of streamChat(history, modelId)) {
        if (event.type === 'text') {
          setMessages((prev) =>
            prev.map((m) => m.id === assistantId ? { ...m, content: m.content + event.content } : m),
          )
          setToolActivity('')
        } else if (event.type === 'tool_use') {
          toolCallsRef.current.push({ label: event.label })
          setToolActivity(event.label)
        } else if (event.type === 'query_rewrite') {
          const buf = toolCallsRef.current
          if (buf.length > 0) {
            buf[buf.length - 1].queryRewrite = { original: event.original, rewritten: event.rewritten }
          }
        } else if (event.type === 'suggestions') {
          setMessages((prev) =>
            prev.map((m) => m.id === assistantId ? { ...m, suggestions: event.videos } : m),
          )
          setToolActivity('')
        } else if (event.type === 'citations') {
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== assistantId) return m
              const existing = m.citations ?? []
              const existingUrls = new Set(existing.map((c) => c.url))
              const fresh = event.sources.filter((s) => !existingUrls.has(s.url))
              if (!fresh.length) return m
              const reindexed = fresh.map((s, i) => ({ ...s, index: existing.length + i + 1 }))
              return { ...m, citations: [...existing, ...reindexed] }
            }),
          )
        } else if (event.type === 'reflection') {
          setToolActivity(`🔍 补充搜索：${event.gap}`)
        }
      }
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, content: `出错了：${String(err)}` } : m,
        ),
      )
    } finally {
      const records = [...toolCallsRef.current]
      if (records.length > 0) {
        setMessages((prev) =>
          prev.map((m) => m.id === assistantId ? { ...m, toolCallRecords: records } : m),
        )
      }
      setLoading(false)
      setToolActivity('')
    }
  }

  const send = () => {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    handleSend(text, messages)
  }

  // Find the user message before this assistant message and re-run
  const regenerate = (assistantMsgId: string) => {
    if (loading) return
    const idx = messages.findIndex((m) => m.id === assistantMsgId)
    if (idx <= 0) return
    const userMsg = messages[idx - 1]
    if (!userMsg || userMsg.role !== 'user') return
    handleSend(userMsg.content, messages.slice(0, idx - 1))
  }

  const copy = async (text: string, msgId: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedId(msgId)
      setTimeout(() => setCopiedId(null), 2000)
    } catch { /* ignore */ }
  }

  const toggleCalls = (msgId: string) => {
    setExpandedCalls((prev) => {
      const next = new Set(prev)
      next.has(msgId) ? next.delete(msgId) : next.add(msgId)
      return next
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const showSuggestions = messages.length === 1 && !loading && suggestions.length > 0

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex justify-end pb-2 shrink-0">
        <button
          onClick={() => { setMessages([WELCOME]); localStorage.removeItem(STORAGE_KEY) }}
          className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
        >
          清除对话
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-1 py-2 space-y-4 min-h-0">
        {messages.map((msg, msgIdx) => (
          <div key={msg.id} className="group">
            {/* Message row */}
            <div className={`flex items-end gap-2 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {msg.role === 'assistant' && (
                <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-xs shrink-0">
                  K
                </div>
              )}
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${
                  msg.role === 'user'
                    ? 'bg-blue-600 text-white rounded-br-sm'
                    : 'bg-gray-800 text-gray-200 rounded-bl-sm'
                }`}
              >
                {msg.role === 'assistant' ? (
                  <div className="prose-custom">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {msg.content || (loading && msg.id === messages[messages.length - 1]?.id ? '▌' : '')}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                )}
              </div>
              {msg.role === 'user' && (
                <div className="w-7 h-7 rounded-full bg-gray-600 flex items-center justify-center text-xs shrink-0">
                  我
                </div>
              )}
            </div>

            {/* Below-bubble content (assistant only) */}
            {msg.role === 'assistant' && (
              <div className="pl-9 mt-1.5 space-y-2">

                {/* ① Action buttons — appear on group hover */}
                {msg.content && (
                  <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-3">
                    <button
                      onClick={() => copy(msg.content, msg.id)}
                      className="text-[11px] text-gray-500 hover:text-gray-300 transition-colors"
                    >
                      {copiedId === msg.id ? '✓ 已复制' : '复制'}
                    </button>
                    {msgIdx > 0 && messages[msgIdx - 1]?.role === 'user' && (
                      <button
                        onClick={() => regenerate(msg.id)}
                        disabled={loading}
                        className="text-[11px] text-gray-500 hover:text-gray-300 disabled:opacity-30 transition-colors"
                      >
                        重新生成
                      </button>
                    )}
                  </div>
                )}

                {/* ② Tool calls panel */}
                {msg.toolCallRecords && msg.toolCallRecords.length > 0 && (
                  <ToolCallsPanel
                    records={msg.toolCallRecords}
                    expanded={expandedCalls.has(msg.id)}
                    onToggle={() => toggleCalls(msg.id)}
                  />
                )}

                {/* ③ Citations */}
                {msg.citations && msg.citations.length > 0 && (
                  <div>
                    <p className="text-xs text-gray-500 mb-1.5">参考来源</p>
                    <div className="flex flex-col gap-1">
                      {msg.citations.map((c) => <CitationCard key={c.index} source={c} />)}
                    </div>
                  </div>
                )}

                {/* ④ YouTube suggestions */}
                {msg.suggestions && msg.suggestions.length > 0 && (
                  <div>
                    <p className="text-xs text-gray-500 mb-1.5">YouTube 推荐视频</p>
                    <div className="flex flex-col gap-1.5">
                      {msg.suggestions.map((v, i) => <SuggestionCard key={i} video={v} />)}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}

        {/* Suggested prompts — only shown on fresh chat */}
        {showSuggestions && (
          <div className="pl-9 space-y-2">
            <p className="text-xs text-gray-500">你可以这样问我：</p>
            <div className="grid grid-cols-2 gap-2">
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  onClick={() => { setInput(s); textareaRef.current?.focus() }}
                  className="text-left text-xs text-gray-400 bg-gray-800/80 hover:bg-gray-700 hover:text-gray-200
                    border border-gray-700 rounded-xl px-3 py-2.5 transition-colors line-clamp-2 leading-relaxed"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* In-flight tool activity indicator */}
        {toolActivity && (
          <div className="flex justify-start items-end gap-2">
            <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-xs shrink-0">
              K
            </div>
            <div className="bg-gray-800 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm text-gray-400 flex items-center gap-2">
              <span className="w-3 h-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin shrink-0" />
              <span>{toolActivity}…</span>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="pt-3 border-t border-gray-800 shrink-0">
        {/* Model selector */}
        <div className="flex items-center gap-2 mb-2">
          <span className="text-xs text-gray-600">模型</span>
          {MODELS.map((m) => (
            <button
              key={m.id}
              onClick={() => { setModelId(m.id); localStorage.setItem(MODEL_STORAGE_KEY, m.id) }}
              disabled={loading}
              className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs transition-colors border disabled:opacity-50 ${
                modelId === m.id
                  ? 'bg-blue-600/20 border-blue-600 text-blue-400'
                  : 'bg-gray-800 border-gray-700 text-gray-500 hover:text-gray-300 hover:border-gray-500'
              }`}
            >
              <span>{m.icon}</span>
              <span>{m.label}</span>
            </button>
          ))}
        </div>
        <div className="flex gap-2 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="问问你的知识库…（Enter 发送，Shift+Enter 换行）"
            rows={2}
            disabled={loading}
            className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white
              placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none disabled:opacity-50"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="px-4 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700
              disabled:text-gray-500 text-white text-sm rounded-xl transition-colors shrink-0"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function ToolCallsPanel({
  records,
  expanded,
  onToggle,
}: {
  records: ToolCallRecord[]
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <div className="text-xs">
      <button
        onClick={onToggle}
        className="flex items-center gap-1.5 text-gray-600 hover:text-gray-400 transition-colors select-none"
      >
        <span className={`transition-transform duration-150 inline-block ${expanded ? 'rotate-90' : ''}`}>▸</span>
        <span>查看工具调用（{records.length} 次）</span>
      </button>
      {expanded && (
        <div className="mt-2 pl-3 border-l border-gray-700 space-y-2.5">
          {records.map((r, i) => (
            <div key={i}>
              <p className="text-gray-500">{r.label}</p>
              {r.queryRewrite && (
                <div className="mt-1 text-[11px] space-y-0.5">
                  <div className="flex items-start gap-1.5">
                    <span className="text-gray-600 shrink-0">原始：</span>
                    <span className="text-gray-500 line-through">{r.queryRewrite.original}</span>
                  </div>
                  <div className="flex items-start gap-1.5">
                    <span className="text-gray-600 shrink-0">改写：</span>
                    <span className="text-blue-400">{r.queryRewrite.rewritten}</span>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function CitationCard({ source }: { source: CitationSource }) {
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-2.5 bg-gray-850 border border-gray-700/60 rounded-lg px-3 py-2
        hover:border-blue-500/50 hover:bg-gray-800 transition-colors group"
    >
      <span className="shrink-0 w-5 h-5 rounded bg-gray-700 flex items-center justify-center
        text-[10px] font-bold text-gray-400 group-hover:text-blue-400 group-hover:bg-blue-900/30">
        {source.index}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-gray-300 group-hover:text-white truncate leading-snug">
          {source.title}
        </p>
        {source.channel && (
          <p className="text-[11px] text-gray-500 truncate">{source.channel}</p>
        )}
      </div>
      <svg className="w-3 h-3 text-gray-600 group-hover:text-blue-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
      </svg>
    </a>
  )
}

function SuggestionCard({ video }: { video: YoutubeVideoSuggestion }) {
  const mins = video.duration ? Math.round(video.duration / 60) : null
  return (
    <a
      href={video.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-start gap-3 bg-gray-850 border border-gray-700 rounded-xl px-3 py-2.5
        hover:border-blue-500 hover:bg-gray-800 transition-colors group"
    >
      <div className="w-8 h-8 rounded-lg bg-red-600 flex items-center justify-center shrink-0 mt-0.5">
        <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="currentColor">
          <path d="M8 5v14l11-7z" />
        </svg>
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm text-gray-200 group-hover:text-white line-clamp-2 leading-snug">
          {video.title}
        </p>
        <p className="text-xs text-gray-500 mt-0.5">
          {video.channel}{mins ? ` · ${mins} 分钟` : ''}
        </p>
      </div>
      <svg className="w-3.5 h-3.5 text-gray-600 group-hover:text-blue-400 shrink-0 mt-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
      </svg>
    </a>
  )
}
