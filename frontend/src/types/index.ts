export interface Video {
  id: string
  title: string
  channel: string
  url: string
  platform: string
  summary: string
  tags: string[]
  category?: string
  related_ids?: string[]
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

export interface YoutubeVideoSuggestion {
  title: string
  url: string
  channel: string
  duration?: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolActivity?: string
  suggestions?: YoutubeVideoSuggestion[]
}

export interface Stats {
  total: number
  total_duration: number
  categories: Record<string, number>
  platforms: Record<string, number>
  top_tags: { tag: string; count: number }[]
  weekly: { label: string; count: number }[]
}

export interface Article {
  filename: string
  topic: string
  date: string
  preview: string
  content: string
}

export interface Recommendation {
  topic: string
  reason: string
  videos: YoutubeVideoSuggestion[]
}

export interface Review {
  filename: string
  date: string
  video_count: number
  preview: string
  content: string
}

export type ActiveTab = 'add' | 'chat' | 'note' | 'stats' | 'review' | 'article'
