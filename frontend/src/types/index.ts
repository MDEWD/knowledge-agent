export interface Video {
  id: string
  title: string
  channel: string
  url: string
  platform: string
  summary: string
  tags: string[]
  obsidian_path: string
  created_at: string
  duration?: number
}

export interface ProcessingEvent {
  step: 'extracting' | 'processing' | 'saving' | 'done' | 'error' | 'ping'
  progress: number
  message: string
  video?: Video
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  searching?: string
}

export type ActiveTab = 'add' | 'chat'
