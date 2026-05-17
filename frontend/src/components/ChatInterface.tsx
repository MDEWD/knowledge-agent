import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { streamChat } from '../api/client'
import type { ChatMessage, Video } from '../types'

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
      content: '你好！我是你的知识库助手。你可以问我：\n\n- 最近学了哪些视频？\n- 某个主题有什么核心观点？\n- 视频里提到了什么方法或概念？',
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [searchingQuery, setSearchingQuery] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, searchingQuery])

  // Inject a prompt when user clicks a video in sidebar
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
    const assistantMsg: ChatMessage = { id: nextId(), role: 'assistant', content: '' }

    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setInput('')
    setLoading(true)
    setSearchingQuery('')

    const history = [...messages, userMsg].map(({ role, content }) => ({ role, content }))

    try {
      for await (const event of streamChat(history)) {
        if (event.type === 'text') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsg.id ? { ...m, content: m.content + event.content } : m,
            ),
          )
          setSearchingQuery('')
        } else if (event.type === 'searching') {
          setSearchingQuery(event.query)
        }
      }
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsg.id
            ? { ...m, content: `出错了：${String(err)}` }
            : m,
        ),
      )
    } finally {
      setLoading(false)
      setSearchingQuery('')
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
          <div
            key={msg.id}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
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
                    {msg.content || (loading ? '▌' : '')}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              )}
            </div>
          </div>
        ))}

        {searchingQuery && (
          <div className="flex justify-start">
            <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-xs shrink-0 mt-0.5 mr-2">
              K
            </div>
            <div className="bg-gray-800 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm text-gray-400 flex items-center gap-2">
              <span className="animate-spin text-xs">⟳</span>
              <span>正在搜索：{searchingQuery}</span>
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
