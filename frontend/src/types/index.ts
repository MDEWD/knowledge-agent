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

export type ActiveTab = 'add' | 'import' | 'chat' | 'note' | 'stats' | 'review' | 'article' | 'recall' | 'graph' | 'agent'

// ── Multi-Agent Orchestrator ──────────────────────────────────────────────────

export interface AgentStep {
  agent: string
  task: string
  status: 'pending' | 'running' | 'done' | 'error'
  summary?: string
}

export type AgentEvent =
  | { type: 'plan'; steps: AgentStep[] }
  | { type: 'agent_start'; agent: string; task: string }
  | { type: 'agent_done'; agent: string; summary: string }
  | { type: 'text'; content: string }
  | { type: 'skills'; skills: { name: string; description: string }[] }
  | { type: 'harness'; budget: BudgetSummary }
  | { type: 'skill_learned'; count: number; names: string[] }
  | { type: 'error'; message: string }
  | { type: 'done' }

// ── RAG Eval ──────────────────────────────────────────────────────────────────

export interface EvalCase {
  question: string
  ground_truth: string
  answer: string
  faithfulness: number
  answer_relevancy: number
  precision_at_3: number
  retrieval_latency_ms: number
  source_title: string
}

export interface EvalResult {
  timestamp: string | null
  case_count?: number
  metrics: {
    faithfulness?: number
    answer_relevancy?: number
    precision_at_3?: number
    avg_retrieval_latency_ms?: number
  }
  per_case: EvalCase[]
}



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

// ── Harness & Skills ──────────────────────────────────────────────────────────

export interface BudgetSummary {
  input_tokens: number
  output_tokens: number
  tool_calls: number
  limits: {
    max_input_tokens: number | null
    max_output_tokens: number | null
    max_tool_calls: number | null
  }
}

export interface SkillEntry {
  skill_id: string
  name: string
  tags: string[]
  created_at: number
  use_count: number
}

export interface HarnessStatus {
  circuit_state: 'closed' | 'open' | 'half-open'
  failure_threshold: number
  recovery_timeout: number
}

