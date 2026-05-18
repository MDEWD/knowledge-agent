import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { streamChat } from '../api/client'
import type { ChatMessage, Video, YoutubeVideoSuggestion } from '../types'

let _idCounter = 0
const nextId = () => String(++_idCounter)

interface Props {
  suggestedVideo?: Video | null
}

export default function ChatInterface({ suggestedVideo }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: nextId(),
      role: 'assistant',
      content: '你好！我是你的知识库助手，支持多种工具来帮你探索知识库。你可以问我：\n\n- 最近学了哪些视频？\n- 对比几个视频的核心观点\n- 某分类下有哪些内容？\n- 帮我生成一篇关于「XX主题」的综合文章',
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [toolActivity, setToolActivity] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, toolActivity])

  useEffect(() => {
    if (suggestedVideo) {
      setInput(`告诉我关于《${suggestedVideo.title}》的核心内容`)
      textareaRef.current?.focus()
    }
  }, [suggestedVideo])

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return

    const userMsg: ChatMessage = { id: nextId(), role: 'user', content: text }
    const assistantId = nextId()
    const assistantMsg: ChatMessage = { id: assistantId, role: 'assistant', content: '' }

    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setInput('')
    setLoading(true)
    setToolActivity('')

    const history = [...messages, userMsg].map(({ role, content }) => ({ role, content }))

    try {
      for await (const event of streamChat(history)) {
        if (event.type === 'text') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + event.content } : m,
            ),
          )
          setToolActivity('')
        } else if (event.type === 'tool_use') {
          setToolActivity(event.label)
        } else if (event.type === 'suggestions') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, suggestions: event.videos } : m,
            ),
          )
          setToolActivity('')
        }
      }
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: `出错了：${String(err)}` }
            : m,
        ),
      )
    } finally {
      setLoading(false)
      setToolActivity('')
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-1 py-2 space-y-4 min-h-0">
        {messages.map((msg) => (
          <div key={msg.id}>
            <div className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {msg.role === 'assistant' && (
                <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-xs shrink-0 mt-0.5 mr-2">
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
            </div>

            {/* YouTube suggestions card */}
            {msg.suggestions && msg.suggestions.length > 0 && (
              <div className="ml-9 mt-2">
                <p className="text-xs text-gray-500 mb-1.5">YouTube 推荐视频</p>
                <div className="flex flex-col gap-1.5">
                  {msg.suggestions.map((v, i) => (
                    <SuggestionCard key={i} video={v} />
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}

        {/* Tool activity indicator */}
        {toolActivity && (
          <div className="flex justify-start">
            <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-xs shrink-0 mt-0.5 mr-2">
              K
            </div>
            <div className="bg-gray-800 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm text-gray-400 flex items-center gap-2">
              <span className="inline-block w-3 h-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <span>{toolActivity}…</span>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="pt-3 border-t border-gray-800">
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
