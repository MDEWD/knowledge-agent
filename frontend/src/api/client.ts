import type { ProcessingEvent, Video, ChatMessage, ChatHistorySession, Stats, Review, YoutubeVideoSuggestion, Recommendation, CitationSource, RecallCard, RecallStats, KnowledgeGraph, UserMemory, MemoryConflict, ImportedNote, AgentEvent, EvalResult, SkillEntry, HarnessStatus, AuthUser, AdminUser, AuthAuditLog } from '../types'
import { authenticatedFetch, refreshSessionRequest } from './authFetch'

const BASE = '/api'

async function apiPayload<T>(res: Response): Promise<T> {
  if (res.ok) return res.json()
  let message = '请求失败，请稍后重试'
  try {
    const payload = await res.json() as { detail?: string | { message?: string } }
    if (typeof payload.detail === 'string') message = payload.detail
    else if (payload.detail?.message) message = payload.detail.message
  } catch {
    // Keep the user-facing fallback when the server did not return JSON.
  }
  throw new Error(message)
}

async function authPayload(res: Response): Promise<{ user: AuthUser }> {
  return apiPayload<{ user: AuthUser }>(res)
}

export interface RegistrationResult {
  user: AuthUser
  requires_verification: boolean
  delivery: 'smtp' | 'console'
  message: string
  dev_code?: string
}

export async function registerWithEmail(
  email: string,
  password: string,
  displayName: string,
): Promise<RegistrationResult> {
  const res = await fetch(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, display_name: displayName }),
  })
  return apiPayload<RegistrationResult>(res)
}

export async function verifyEmailCode(email: string, code: string): Promise<AuthUser> {
  const res = await fetch(`${BASE}/auth/verify-email`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, code }),
  })
  return (await authPayload(res)).user
}

export async function resendVerificationCode(email: string): Promise<{ message: string; dev_code?: string }> {
  const res = await fetch(`${BASE}/auth/resend-verification`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  return apiPayload(res)
}

export async function requestPasswordReset(email: string): Promise<{ message: string }> {
  const res = await fetch(`${BASE}/auth/forgot-password`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  return apiPayload(res)
}

export async function resetPasswordWithCode(email: string, code: string, newPassword: string): Promise<{ message: string }> {
  const res = await fetch(`${BASE}/auth/reset-password`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, code, new_password: newPassword }),
  })
  return apiPayload(res)
}

export async function loginWithEmail(email: string, password: string): Promise<AuthUser> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  return (await authPayload(res)).user
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  return (await authPayload(await fetch(`${BASE}/auth/me`))).user
}

export async function refreshAuthSession(): Promise<AuthUser> {
  return (await refreshSessionRequest()).user
}

export async function logoutAuthSession(): Promise<void> {
  await fetch(`${BASE}/auth/logout`, { method: 'POST' })
}

export async function fetchAdminUsers(params: { q?: string; role?: string; status?: string } = {}): Promise<{ users: AdminUser[]; total: number }> {
  const query = new URLSearchParams()
  if (params.q) query.set('q', params.q)
  if (params.role) query.set('role', params.role)
  if (params.status) query.set('status', params.status)
  return apiPayload(await fetch(`${BASE}/admin/users?${query}`))
}

export async function updateAdminUser(userId: string, patch: { role?: string; status?: string }): Promise<AuthUser> {
  const res = await fetch(`${BASE}/admin/users/${encodeURIComponent(userId)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
  })
  return (await authPayload(res)).user
}

export async function revokeAdminUserSessions(userId: string): Promise<number> {
  const payload = await apiPayload<{ revoked: number }>(await fetch(
    `${BASE}/admin/users/${encodeURIComponent(userId)}/revoke-sessions`, { method: 'POST' },
  ))
  return payload.revoked
}

export async function fetchAuthAuditLogs(): Promise<AuthAuditLog[]> {
  const payload = await apiPayload<{ logs: AuthAuditLog[] }>(await fetch(`${BASE}/admin/audit-logs`))
  return payload.logs
}

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
  | { type: 'query_rewrite'; original: string; rewritten: string }
  | { type: 'suggestions'; videos: YoutubeVideoSuggestion[] }
  | { type: 'citations'; sources: CitationSource[] }
  | { type: 'reflection'; gap: string }
  | { type: 'done' }

export async function* streamChat(
  messages: Pick<ChatMessage, 'role' | 'content'>[],
  model = 'deepseek',
): AsyncGenerator<ChatEvent> {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, model }),
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

export async function fetchChatHistory(): Promise<ChatHistorySession | null> {
  const res = await fetch(`${BASE}/chat/history`)
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json() as { session: ChatHistorySession | null }
  return data.session
}

export async function saveChatHistory(
  sessionId: string | null,
  messages: ChatMessage[],
  model: string,
): Promise<ChatHistorySession> {
  const res = await fetch(`${BASE}/chat/history`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, messages, model }),
  })
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json() as { session: ChatHistorySession }
  return data.session
}

export async function deleteChatHistory(sessionId: string): Promise<void> {
  const res = await fetch(`${BASE}/chat/history/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
  if (!res.ok && res.status !== 404) throw new Error(await res.text())
}

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


// ── Multi-Agent Orchestrator ──────────────────────────────────────────────────

export async function* streamAgentRun(task: string): AsyncGenerator<AgentEvent> {
  const res = await fetch(`${BASE}/agent/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task }),
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
      try { yield JSON.parse(line.slice(6)) as AgentEvent } catch { /* ignore */ }
    }
  }
}

export async function confirmAgentRun(runId: string): Promise<void> {
  await fetch(`${BASE}/agent/confirm/${runId}`, { method: 'POST' })
}


// ── DeepResearch mode (自进化+对抗降噪循环) ─────────────────────────────────

export interface DeepResearchTurn {
  question: string
  answer: string
}

export interface DeepResearchEvidence {
  source_id?: string
  query: string
  title: string
  url: string
  snippet: string
  status: 'found' | 'summarized'
  published_at?: string | null
  source_type?: string
  authority_score?: number
  freshness_score?: number
}

export interface DeepResearchSessionSummary {
  id: string
  title: string
  run_id: string
  created_at: string
  updated_at: string
  turn_count: number
}

export interface DeepResearchSession {
  id: string
  title: string
  run_id: string
  turns: DeepResearchTurn[]
  evidence: DeepResearchEvidence[]
  created_at: string
  updated_at: string
}

export interface ActiveDeepResearchRun {
  run_id: string
  session_id: string
  task: string
  status: string
  started_at: string
  last_seq: number
}

async function* readAgentEventStream(
  res: Response,
): AsyncGenerator<AgentEvent> {
  if (!res.ok) throw new Error(await res.text())
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try { yield JSON.parse(line.slice(6)) as AgentEvent } catch { /* ignore */ }
    }
  }
}

export async function* streamDeepAgentRun(
  task: string,
  history: DeepResearchTurn[] = [],
  sessionId?: string,
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const res = await authenticatedFetch(`${BASE}/agent/deep-run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task, history, session_id: sessionId }),
    signal,
  })
  yield* readAgentEventStream(res)
}

export async function fetchActiveDeepResearchRuns(): Promise<ActiveDeepResearchRun[]> {
  const res = await authenticatedFetch(`${BASE}/agent/deep-runs/active`)
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json() as { runs: ActiveDeepResearchRun[] }
  return data.runs
}

export async function* streamDeepAgentRunEvents(
  runId: string,
  after = 0,
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const query = new URLSearchParams({ after: String(Math.max(0, after)) })
  const res = await authenticatedFetch(
    `${BASE}/agent/deep-run/${encodeURIComponent(runId)}/events?${query}`,
    { signal },
  )
  yield* readAgentEventStream(res)
}

export async function cancelDeepAgentRun(runId: string): Promise<void> {
  const res = await authenticatedFetch(`${BASE}/agent/deep-run/${encodeURIComponent(runId)}/cancel`, {
    method: 'POST',
  })
  if (!res.ok && res.status !== 404) throw new Error(await res.text())
}

export async function fetchDeepResearchHistory(): Promise<DeepResearchSessionSummary[]> {
  const res = await authenticatedFetch(`${BASE}/agent/deep-history`)
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json() as { sessions: DeepResearchSessionSummary[] }
  return data.sessions
}

export async function fetchDeepResearchSession(sessionId: string): Promise<DeepResearchSession> {
  const res = await authenticatedFetch(`${BASE}/agent/deep-history/${encodeURIComponent(sessionId)}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchMemoryConflicts(): Promise<MemoryConflict[]> {
  const res = await fetch(`${BASE}/memory/conflicts?status=pending`)
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json() as { conflicts: MemoryConflict[] }
  return data.conflicts
}

export async function resolveMemoryConflict(
  conflictId: string,
  winnerMemoryId: number,
  reason: string,
): Promise<void> {
  const res = await fetch(`${BASE}/memory/conflicts/${encodeURIComponent(conflictId)}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ winner_memory_id: winnerMemoryId, reason }),
  })
  if (!res.ok) throw new Error(await res.text())
}

export async function saveDeepResearchSession(session: {
  id: string
  title: string
  run_id: string
  turns: DeepResearchTurn[]
  evidence?: DeepResearchEvidence[]
}): Promise<DeepResearchSession> {
  const res = await authenticatedFetch(`${BASE}/agent/deep-history/${encodeURIComponent(session.id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(session),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteDeepResearchSession(sessionId: string): Promise<void> {
  const res = await authenticatedFetch(`${BASE}/agent/deep-history/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error(await res.text())
}

export async function exportDeepResearchReport(
  title: string,
  content: string,
  format: 'md' | 'pdf',
): Promise<Blob> {
  const res = await authenticatedFetch(`${BASE}/agent/deep-export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, content, format }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.blob()
}


// ── RAG Eval ──────────────────────────────────────────────────────────────────

export async function generateEvalCases(force = false): Promise<{ count: number }> {
  const res = await fetch(`${BASE}/evals/generate?force=${force}`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function runEvals(): Promise<EvalResult> {
  const res = await fetch(`${BASE}/evals/run`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchEvalResults(): Promise<EvalResult> {
  const res = await fetch(`${BASE}/evals/results`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}


// ── Skills library ────────────────────────────────────────────────────────────

export async function fetchSkills(): Promise<{ skills: SkillEntry[] }> {
  const res = await fetch(`${BASE}/skills`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteSkill(skillId: string): Promise<void> {
  const res = await fetch(`${BASE}/skills/${skillId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

export async function fetchHarnessStatus(): Promise<HarnessStatus> {
  const res = await fetch(`${BASE}/harness/status`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

