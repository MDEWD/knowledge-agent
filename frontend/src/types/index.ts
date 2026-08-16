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

export interface ToolCallRecord {
  label: string
  queryRewrite?: { original: string; rewritten: string }
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolActivity?: string
  suggestions?: YoutubeVideoSuggestion[]
  citations?: CitationSource[]
  toolCallRecords?: ToolCallRecord[]
}

export interface ChatHistorySession {
  id: string
  title: string
  model: string
  messages: ChatMessage[]
  created_at?: string
  updated_at?: string
}

export interface Stats {
  total: number
  total_duration: number
  categories: Record<string, number>
  platforms: Record<string, number>
  top_tags: { tag: string; count: number }[]
  weekly: { label: string; count: number }[]
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

export type ActiveTab = 'add' | 'import' | 'ai' | 'note' | 'stats' | 'deep'

// ── Multi-Agent Orchestrator ──────────────────────────────────────────────────

export interface AgentStep {
  agent: string
  task: string
  status: 'pending' | 'running' | 'done' | 'error'
  summary?: string
  stop_reason?: string
}

export type AgentEvent =
  | { type: 'plan'; steps: AgentStep[] }
  | { type: 'agent_start'; agent: string; task: string }
  | { type: 'agent_done'; agent: string; summary: string; stop_reason?: string }
  | { type: 'text'; content: string }
  | { type: 'skills'; skills: { name: string; description: string }[] }
  | { type: 'harness'; budget: BudgetSummary }
  | { type: 'skill_learned'; count: number; names: string[] }
  | { type: 'error'; message: string }
  | { type: 'done' }
  | { type: 'hitl_confirm'; run_id: string; steps: AgentStep[] }
  | { type: 'sub_agent_tool'; agent: string; tool: string; label: string; args?: string }
  | { type: 'collaboration'; from_agent: string; to_agent: string; topic: string; reason: string }
  // ── DeepResearch 模式新增事件 ──
  | { type: 'iteration'; iter: number; max: number }
  | { type: 'phase_status'; phase: string; label: string; iteration?: number }
  | { type: 'research_source'; agent: string; query: string; title: string; url: string; snippet: string; status: 'found' | 'summarized'; source_id?: string; published_at?: string | null; source_type?: string; authority_score?: number; freshness_score?: number }
  | { type: 'research_brief'; content: string }
  | { type: 'draft_update'; content: string; iteration: number; avg_score: number | null }
  | { type: 'critique'; author: string; concern: string; iteration: number }
  | { type: 'eval_score'; comprehensive: number; accuracy: number; coherence: number; average: number; reason: string; iteration: number }
  | { type: 'run_started'; run_id: string }
  | { type: 'run_resumed'; run_id: string; phase: string }
  | { type: 'stop_decision'; reason: string; detail: string; forced: boolean }
  | { type: 'citation_validation'; valid: boolean; issues: { code: string; message: string; url?: string }[]; evidence_count: number; sanitized?: boolean }
  | { type: 'report_replace'; content: string }
  | { type: 'research_state'; run_id: string; phase: string; status: string; iteration: number; evidence_count: number; open_critiques: number; budget: BudgetSummary }
  | { type: 'deep_research_eval'; passed: boolean; citation_valid: boolean; evidence_coverage: number; source_diversity: number; critique_resolution_rate: number; completed: boolean; protocol_errors: number; reasons: string[] }

// DeepResearch 运行模式
export type AgentRunMode = 'quick' | 'deep'

// ── RAG Eval ──────────────────────────────────────────────────────────────────

export interface EvalCase {
  question: string
  ground_truth: string
  answer: string
  faithfulness: number
  answer_relevancy: number
  completeness: number
  coherence: number
  precision_at_3: number
  retrieval_latency_ms: number
  source_title: string
  rubric?: { faithfulness: number; relevancy: number; completeness: number; coherence: number; mean: number }
}

export interface EvalResult {
  timestamp: string | null
  case_count?: number
  metrics: {
    faithfulness?: number
    answer_relevancy?: number
    completeness?: number
    coherence?: number
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

export interface MemoryConflict {
  id: string
  existing_memory_id: number
  candidate_memory_id: number
  conflict_type: string
  existing_content: string
  candidate_content: string
  existing_scope: Record<string, string>
  candidate_scope: Record<string, string>
  created_at: string
}

// ── Harness & Skills ──────────────────────────────────────────────────────────

export interface BudgetSummary {
  input_tokens: number
  output_tokens: number
  tool_calls: number
  cost_usd?: number
  by_role?: Record<string, { input_tokens: number; output_tokens: number; calls: number; cost_usd: number }>
  by_tool?: Record<string, { calls: number; cost_usd: number }>
  exceeded?: string[]
  limits: {
    max_input_tokens: number | null
    max_output_tokens: number | null
    max_tool_calls: number | null
    max_cost_usd?: number | null
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

