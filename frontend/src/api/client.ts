import type { ProcessingEvent, Video, ChatMessage, Stats, Review, Article, YoutubeVideoSuggestion, Recommendation, CitationSource, RecallCard, RecallStats, KnowledgeGraph, UserMemory, ImportedNote } from '../types'

const BASE = '/api'

export async function checkDuplicate(url: string): Promise<{ duplicate: boolean; video?: Video }> {
  const res = await fetch(`${BASE}/videos/check?url=${encodeURIComponent(url)}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function submitVideo(url: string, platform: string, translate: boolean, diarize: boolean): Promise<string> {
  const res = await fetch(`${BASE}/process-video`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, platform, translate, diarize }),
  })
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json()
  return data.task_id as string
}

export function watchTask(
  taskId: string,
  onEvent: (e: ProcessingEvent) => void,
): () => void {
  const es = new EventSource(`${BASE}/status/${taskId}`)
  es.onmessage = (e) => {
    try {
      const event: ProcessingEvent = JSON.parse(e.data)
      onEvent(event)
      if (event.step === 'done' || event.step === 'error') es.close()
    } catch {
      // ignore
    }
  }
  es.onerror = () => es.close()
  return () => es.close()
}

export async function fetchStats(): Promise<Stats> {
  const res = await fetch(`${BASE}/stats`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchVideos(): Promise<Video[]> {
  const res = await fetch(`${BASE}/videos`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteVideo(id: string): Promise<void> {
  const res = await fetch(`${BASE}/videos/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

export async function getNote(id: string): Promise<{ insights: string }> {
  const res = await fetch(`${BASE}/videos/${id}/note`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function updateNote(id: string, insights: string): Promise<void> {
  const res = await fetch(`${BASE}/videos/${id}/note`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ insights }),
  })
  if (!res.ok) throw new Error(await res.text())
}

export async function fetchArticles(): Promise<Article[]> {
  const res = await fetch(`${BASE}/articles`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function generateArticle(
  topic: string,
): Promise<{ article: string; path: string; source_count: number }> {
  const res = await fetch(`${BASE}/generate-article`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function generateReview(days = 7): Promise<{
  report: string
  video_count: number
  saved_path: string
  date: string
  video_titles: string[]
}> {
  const res = await fetch(`${BASE}/review/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ days }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchRecommendations(): Promise<Recommendation[]> {
  const res = await fetch(`${BASE}/recommendations`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchReviews(): Promise<Review[]> {
  const res = await fetch(`${BASE}/reviews`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

type ReviewChatEvent =
  | { type: 'text'; content: string }
  | { type: 'done' }

export async function* streamReviewChat(
  reviewContent: string,
  messages: Pick<ChatMessage, 'role' | 'content'>[],
): AsyncGenerator<ReviewChatEvent> {
  const res = await fetch(`${BASE}/review/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ review_content: reviewContent, messages }),
  })
  if (!res.ok) throw new Error(await res.text())
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        yield JSON.parse(line.slice(6)) as ReviewChatEvent
      } catch { /* ignore */ }
    }
  }
}

type ChatEvent =
  | { type: 'text'; content: string }
  | { type: 'tool_use'; tool: string; label: string }
  | { type: 'suggestions'; videos: YoutubeVideoSuggestion[] }
  | { type: 'citations'; sources: CitationSource[] }
  | { type: 'done' }

export async function* streamChat(
  messages: Pick<ChatMessage, 'role' | 'content'>[],
): AsyncGenerator<ChatEvent> {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
  })

  if (!res.ok) throw new Error(await res.text())
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const event: ChatEvent = JSON.parse(line.slice(6))
        yield event
      } catch {
        // ignore
      }
    }
  }
}

// ── Active Recall ─────────────────────────────────────────────────────────────

export async function generateRecallCards(videoId: string, count = 5): Promise<RecallCard[]> {
  const res = await fetch(`${BASE}/recall/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_id: videoId, count }),
  })
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json()
  return data.cards as RecallCard[]
}

export async function fetchDueCards(): Promise<{ cards: RecallCard[]; stats: RecallStats }> {
  const res = await fetch(`${BASE}/recall/due`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchAllCards(): Promise<{ cards: RecallCard[]; stats: RecallStats }> {
  const res = await fetch(`${BASE}/recall/all`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function reviewRecallCard(cardId: string, quality: number): Promise<RecallCard> {
  const res = await fetch(`${BASE}/recall/review/${cardId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ quality }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteRecallCards(videoId: string): Promise<void> {
  const res = await fetch(`${BASE}/recall/video/${videoId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

// ── Knowledge Graph ───────────────────────────────────────────────────────────

export async function fetchGraph(): Promise<KnowledgeGraph> {
  const res = await fetch(`${BASE}/graph`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function rebuildGraph(): Promise<KnowledgeGraph> {
  const res = await fetch(`${BASE}/graph/rebuild`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// ── Long-term Memory ──────────────────────────────────────────────────────────

export async function fetchMemory(): Promise<UserMemory> {
  const res = await fetch(`${BASE}/memory`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function updateMemory(mem: Partial<UserMemory>): Promise<UserMemory> {
  const res = await fetch(`${BASE}/memory`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(mem),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function resetMemory(): Promise<UserMemory> {
  const res = await fetch(`${BASE}/memory/reset`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// ── Note Import ───────────────────────────────────────────────────────────────

export async function importNotes(
  files: File[],
): Promise<{ tasks: { task_id: string; filename: string }[] }> {
  const fd = new FormData()
  for (const f of files) fd.append('files', f)
  const res = await fetch(`${BASE}/notes/import`, { method: 'POST', body: fd })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchImportedNotes(): Promise<ImportedNote[]> {
  const res = await fetch(`${BASE}/notes`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteImportedNote(id: string): Promise<void> {
  const res = await fetch(`${BASE}/notes/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

