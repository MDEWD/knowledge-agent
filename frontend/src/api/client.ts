import type { ProcessingEvent, Video, ChatMessage, Stats, Review, Article, YoutubeVideoSuggestion, Recommendation } from '../types'

const BASE = '/api'

export async function checkDuplicate(url: string): Promise<{ duplicate: boolean; video?: Video }> {
  const res = await fetch(`${BASE}/videos/check?url=${encodeURIComponent(url)}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function submitVideo(url: string, platform: string): Promise<string> {
  const res = await fetch(`${BASE}/process-video`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, platform }),
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
