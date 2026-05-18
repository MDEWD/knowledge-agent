import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { fetchArticles, generateArticle } from '../api/client'
import type { Article } from '../types'

export default function ArticlePanel() {
  const [articles, setArticles] = useState<Article[]>([])
  const [selected, setSelected] = useState<Article | null>(null)
  const [topic, setTopic] = useState('')
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')
  const [genInfo, setGenInfo] = useState<{ source_count: number; path: string } | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    fetchArticles().then(setArticles).catch(console.error)
  }, [])

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault()
    const t = topic.trim()
    if (!t) return
    setGenerating(true)
    setError('')
    setGenInfo(null)
    try {
      const result = await generateArticle(t)
      const newArticle: Article = {
        filename: result.path.split('/').pop() ?? `${t}.md`,
        topic: t,
        date: new Date().toISOString().slice(0, 10),
        preview: result.article.slice(0, 200),
        content: result.article,
      }
      setGenInfo({ source_count: result.source_count, path: result.path })
      setArticles((prev) => [newArticle, ...prev.filter((a) => a.topic !== t)])
      setSelected(newArticle)
      setTopic('')
    } catch (err) {
      setError(String(err))
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="flex h-full gap-4 min-h-0">
      {/* Left: generate form + article list */}
      <div className="w-64 shrink-0 flex flex-col gap-3">
        {/* Generate form */}
        <form onSubmit={handleGenerate} className="bg-gray-800 rounded-xl p-4 space-y-3">
          <p className="text-sm font-medium text-white">生成综合文章</p>
          <p className="text-xs text-gray-500">基于知识库中的相关内容，AI 自动整合多个视频的观点</p>
          <input
            ref={inputRef}
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="输入主题，如：AI Agent 设计"
            disabled={generating}
            className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm text-white
              placeholder-gray-500 focus:outline-none focus:border-blue-500 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={generating || !topic.trim()}
            className="w-full py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700
              disabled:text-gray-500 text-white text-sm rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            {generating ? (
              <>
                <span className="inline-block w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                生成中…
              </>
            ) : (
              '生成文章'
            )}
          </button>
          {error && <p className="text-xs text-red-400">{error}</p>}
          {genInfo && (
            <p className="text-xs text-green-400">
              已保存到 Obsidian，综合了 {genInfo.source_count} 个来源
            </p>
          )}
        </form>

        {/* Article list */}
        <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5">
          {articles.length === 0 ? (
            <p className="text-xs text-gray-600 text-center pt-6">暂无文章</p>
          ) : (
            articles.map((a) => (
              <button
                key={a.filename}
                onClick={() => setSelected(a)}
                className={`w-full text-left px-3 py-2.5 rounded-xl transition-colors ${
                  selected?.filename === a.filename
                    ? 'bg-blue-600/20 border border-blue-500/50'
                    : 'bg-gray-800 border border-transparent hover:border-gray-700'
                }`}
              >
                <p className="text-sm text-gray-200 font-medium truncate">{a.topic}</p>
                <p className="text-xs text-gray-500 mt-0.5">{a.date}</p>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Right: article content */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        {selected ? (
          <div className="bg-gray-800 rounded-xl p-6">
            <div className="flex items-start justify-between gap-4 mb-5 pb-4 border-b border-gray-700">
              <div>
                <h2 className="text-base font-semibold text-white">{selected.topic}</h2>
                <p className="text-xs text-gray-500 mt-0.5">{selected.date} · {selected.filename}</p>
              </div>
            </div>
            <div className="prose-custom text-sm">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{selected.content}</ReactMarkdown>
            </div>
          </div>
        ) : (
          <div className="h-full flex flex-col items-center justify-center gap-3 text-gray-600">
            <div className="text-4xl">📝</div>
            <p className="text-sm">
              {articles.length > 0 ? '选择左侧文章查看内容' : '输入主题，生成你的第一篇综合文章'}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
