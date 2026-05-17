import type { ProcessingEvent, Video, ChatMessage } from '../types'

const BASE = '/api'

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

export async function fetchVideos(): Promise<Video[]> {
  const res = await fetch(`${BASE}/videos`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteVideo(id: string): Promise<void> {
  const res = await fetch(`${BASE}/videos/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

type ChatEvent =
  | { type: 'text'; content: string }
  | { type: 'searching'; query: string }
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
