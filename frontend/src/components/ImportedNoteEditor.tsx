import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { fetchImportedNote } from '../api/client'
import type { ImportedNote } from '../types'

export default function ImportedNoteEditor({ note }: { note: ImportedNote }) {
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    fetchImportedNote(note.id)
      .then((data) => setContent(data.content))
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false))
  }, [note.id])

  if (loading) return <div className="flex h-full items-center justify-center text-sm text-gray-500">加载中…</div>
  if (error) return <div className="flex h-full items-center justify-center text-sm text-red-400">{error}</div>

  return (
    <div className="h-full overflow-y-auto rounded-lg border border-gray-800 bg-gray-900 p-6">
      <h1 className="mb-2 text-xl font-semibold text-white">{note.title}</h1>
      <p className="mb-6 text-xs text-gray-500">{note.source_file} · {note.file_type.toUpperCase()}</p>
      <article className="prose prose-invert prose-sm max-w-none">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </article>
    </div>
  )
}
