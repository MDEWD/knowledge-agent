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

export interface ImportedNote {
  id: string
  title: string
  source_file: string
  file_type: string
  summary: string
  category?: string
  tags: string[]
  obsidian_path: string
  created_at: string
  word_count: number
  url: string
}

export interface ProcessingEvent {
  step: 'extracting' | 'processing' | 'saving' | 'done' | 'error' | 'ping'
  progress: number
  message: string
  video?: Video
  note?: ImportedNote
}

export interface YoutubeVideoSuggestion {
  title: string
  url: string
  channel: string
  duration?: number
}

export interface CitationSource {
  index: number
  title: string
  url: string
  channel: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolActivity?: string
  suggestions?: YoutubeVideoSuggestion[]
  citations?: CitationSource[]
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

export type ActiveTab = 'add' | 'import' | 'chat' | 'note' | 'stats' | 'review' | 'article' | 'recall' | 'graph'

// ── Active Recall ─────────────────────────────────────────────────────────────

export interface RecallCard {
  id: string
  video_id: string
  video_title: string
  question: string
  answer: string
  next_review: string
  interval: number
  ease_factor: number
  repetitions: number
  last_quality?: number
  last_reviewed?: string
}

export interface RecallStats {
  total: number
  due_today: number
  mastered: number
  learning: number
}

// ── Knowledge Graph ───────────────────────────────────────────────────────────

export interface GraphNode {
  id: string
  label: string
  type: 'video' | 'concept'
  category: string
  url?: string
  video_id?: string
  shared_count?: number
}

export interface GraphEdge {
  source: string
  target: string
  type: 'mentions' | 'related'
}

export interface KnowledgeGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// ── Long-term Memory ──────────────────────────────────────────────────────────

export interface UserMemory {
  interests: string[]
  learning_goals: string[]
  gaps: string[]
  key_insights: string[]
  summary: string
  updated_at: string
}

