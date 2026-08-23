import { useCallback, useEffect, useRef, useState } from 'react'
import { importNotes, fetchImportedNotes, deleteImportedNote, watchTask } from '../api/client'
import type { ImportedNote, ProcessingEvent } from '../types'

const ACCEPTED = '.md,.pdf,.txt,.docx,.doc'
const ACCEPTED_EXTS = new Set(['md', 'pdf', 'txt', 'docx', 'doc'])

interface UploadTask {
  taskId: string
  filename: string
  event: ProcessingEvent | null
}

const FILE_TYPE_STYLE: Record<string, string> = {
  md: 'bg-purple-900/40 text-purple-300 border-purple-800',
  pdf: 'bg-red-900/40 text-red-300 border-red-800',
  txt: 'bg-gray-700 text-gray-400 border-gray-600',
  docx: 'bg-blue-900/40 text-blue-300 border-blue-800',
  doc: 'bg-blue-900/40 text-blue-300 border-blue-800',
}

const STEP_LABELS: Record<string, string> = {
  extracting: '读取文件',
  processing: 'AI 分析中',
  saving: '写入存储',
  done: '完成',
  error: '出错',
}

export default function NoteImportPanel({ onNoteAdded }: { onNoteAdded?: () => void }) {
  const [tasks, setTasks] = useState<UploadTask[]>([])
  const [notes, setNotes] = useState<ImportedNote[]>([])
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const stopFns = useRef<Map<string, () => void>>(new Map())

  const loadNotes = async () => {
    try { setNotes(await fetchImportedNotes()) } catch { /* ignore */ }
  }

  useEffect(() => {
    loadNotes()
    return () => stopFns.current.forEach((s) => s())
  }, [])

  const processFiles = async (files: File[]) => {
    const valid = files.filter((f) => {
      const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
      return ACCEPTED_EXTS.has(ext)
    })
    if (!valid.length) return

    setUploading(true)
    try {
      const { tasks: newTasks } = await importNotes(valid)

      const initial: UploadTask[] = newTasks.map((t) => ({
        taskId: t.task_id,
        filename: t.filename,
        event: { step: 'extracting', progress: 5, message: '已提交，等待处理…' },
      }))
      setTasks((prev) => [...initial, ...prev])

      for (const t of newTasks) {
        const stop = watchTask(t.task_id, (ev) => {
          setTasks((prev) =>
            prev.map((ut) => (ut.taskId === t.task_id ? { ...ut, event: ev } : ut)),
          )
          if (ev.step === 'done' || ev.step === 'error') {
            if (ev.step === 'done') { loadNotes(); onNoteAdded?.() }
            stopFns.current.get(t.task_id)?.()
            stopFns.current.delete(t.task_id)
          }
        })
        stopFns.current.set(t.task_id, stop)
      }
    } catch (err) {
      alert(String(err))
    } finally {
      setUploading(false)
    }
  }

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    processFiles(Array.from(e.target.files ?? []))
    e.target.value = ''
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    processFiles(Array.from(e.dataTransfer.files))
  }, [])

  const handleDelete = async (id: string) => {
    await deleteImportedNote(id)
    setNotes((prev) => prev.filter((n) => n.id !== id))
  }

  const clearFinished = () =>
    setTasks((prev) => prev.filter((t) => t.event?.step !== 'done' && t.event?.step !== 'error'))

  const activeTasks = tasks.filter((t) => t.event?.step !== 'done' && t.event?.step !== 'error')
  const doneTasks = tasks.filter((t) => t.event?.step === 'done' || t.event?.step === 'error')

  return (
    <div className="h-full overflow-y-auto pb-4">
      <div className="mx-auto w-full max-w-4xl">
        <div className="mb-6">
          <h2 className="text-lg font-semibold text-white mb-1">导入本地笔记</h2>
          <p className="text-sm text-gray-400">
            将笔记导入知识库，与视频内容一起参与语义检索和 AI 对话
          </p>
        </div>

        <div className="space-y-6">
          <section className="space-y-5">
            {/* Drop zone */}
            <div
              onClick={() => !uploading && fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
              onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false) }}
              onDrop={onDrop}
              className={`relative flex min-h-80 flex-col items-center justify-center rounded-2xl border-2 border-dashed p-10 text-center transition-all
                ${uploading ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                ${dragging ? 'border-blue-400 bg-blue-500/10 scale-[1.01]' : 'border-gray-700 hover:border-gray-500 hover:bg-gray-800/20'}`}
            >
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={ACCEPTED}
                onChange={onFileChange}
                className="hidden"
                disabled={uploading}
              />
              <div className="text-5xl mb-3 select-none">{dragging ? '⬇️' : '📂'}</div>
              <p className="text-sm font-medium text-gray-200 mb-1">
                {dragging ? '松开以上传' : '点击上传或拖拽文件到此处'}
              </p>
              <p className="text-xs text-gray-500 mb-4">支持同时上传多个文件</p>
              <div className="flex justify-center gap-2">
                {['MD', 'PDF', 'TXT', 'DOCX', 'DOC'].map((f) => (
                  <span key={f} className="px-2.5 py-1 rounded-lg bg-gray-800 border border-gray-700 text-xs text-gray-400 font-mono">
                    {f}
                  </span>
                ))}
              </div>
            </div>

            {activeTasks.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs text-gray-500 uppercase tracking-wide">处理中 ({activeTasks.length})</p>
                {activeTasks.map((t) => <ProgressCard key={t.taskId} task={t} />)}
              </div>
            )}

            {doneTasks.length > 0 && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <p className="text-xs text-gray-500 uppercase tracking-wide">本次上传结果</p>
                  <button onClick={clearFinished} className="text-xs text-gray-600 hover:text-gray-400">清除</button>
                </div>
                {doneTasks.map((t) => (
                  <div
                    key={t.taskId}
                    className={`rounded-xl px-4 py-2.5 border text-sm ${
                      t.event?.step === 'done'
                        ? 'bg-green-900/20 border-green-800 text-green-400'
                        : 'bg-red-900/20 border-red-800 text-red-400'
                    }`}
                  >
                    <span className="mr-2">{t.event?.step === 'done' ? '✓' : '✕'}</span>
                    <span className="truncate">{t.filename}</span>
                    {t.event?.step === 'error' && (
                      <span className="text-xs ml-2 opacity-70">— {t.event.message}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Notes library */}
          <section className="min-h-80 rounded-2xl border border-gray-700 bg-gray-800/20 p-4">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-xs text-gray-500 uppercase tracking-wide">
                笔记库
                {notes.length > 0 && (
                  <span className="ml-2 px-1.5 py-0.5 bg-gray-700 rounded text-gray-400">{notes.length}</span>
                )}
              </p>
            </div>
            {notes.length === 0 ? (
              <div className="flex min-h-64 flex-col items-center justify-center text-center">
                <p className="text-4xl mb-3">📝</p>
                <p className="text-sm text-gray-500">暂无导入的笔记</p>
                <p className="text-xs text-gray-600 mt-1">导入后可在「AI 对话」中直接引用</p>
              </div>
            ) : (
              <div className="max-h-[calc(100vh-14rem)] space-y-2 overflow-y-auto pr-1">
                {notes.map((n) => (
                  <NoteCard key={n.id} note={n} onDelete={() => handleDelete(n.id)} />
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

function ProgressCard({ task }: { task: UploadTask }) {
  const ev = task.event
  const isError = ev?.step === 'error'
  return (
    <div className={`rounded-xl px-4 py-3 border ${isError ? 'border-red-800 bg-red-900/10' : 'border-gray-700 bg-gray-800'}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-gray-300 truncate pr-2">{task.filename}</span>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-gray-500">{STEP_LABELS[ev?.step ?? ''] ?? ev?.step}</span>
          <span className="text-xs text-gray-600">{ev?.progress}%</span>
        </div>
      </div>
      <div className="w-full bg-gray-700 rounded-full h-1 mb-1.5">
        <div
          className={`h-1 rounded-full transition-all duration-500 ${isError ? 'bg-red-500' : 'bg-blue-500'}`}
          style={{ width: `${ev?.progress ?? 0}%` }}
        />
      </div>
      <p className="text-xs text-gray-500 truncate">{ev?.message}</p>
    </div>
  )
}

function NoteCard({ note, onDelete }: { note: ImportedNote; onDelete: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const words = note.word_count >= 1000
    ? `${(note.word_count / 1000).toFixed(1)}k`
    : String(note.word_count)
  const typeStyle = FILE_TYPE_STYLE[note.file_type] ?? 'bg-gray-700 text-gray-400 border-gray-600'

  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-750 select-none"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className={`shrink-0 px-1.5 py-0.5 rounded border text-[10px] font-bold uppercase ${typeStyle}`}>
          {note.file_type}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-white truncate font-medium">{note.title}</p>
          <p className="text-xs text-gray-500 mt-0.5">
            {note.category} · {words} 字 · {note.created_at.slice(0, 10)}
          </p>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {note.tags.slice(0, 2).map((t) => (
            <span key={t} className="px-1.5 py-0.5 bg-gray-700 text-gray-500 rounded text-[10px]">
              {t}
            </span>
          ))}
          <button
            onClick={(e) => { e.stopPropagation(); onDelete() }}
            className="ml-1 text-gray-600 hover:text-red-400 transition-colors px-1 text-sm"
            title="删除"
          >
            ✕
          </button>
        </div>
      </div>

      {expanded && (
        <div className="px-4 pb-4 border-t border-gray-700 space-y-2">
          {note.summary && (
            <p className="text-xs text-gray-400 leading-relaxed mt-2">{note.summary}</p>
          )}
          <p className="text-xs text-gray-600">
            来源文件：{note.source_file}
          </p>
          {note.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {note.tags.map((t) => (
                <span key={t} className="px-1.5 py-0.5 bg-gray-700/60 text-gray-500 rounded text-[10px]">
                  #{t}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
