import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  cancelDeepAgentRun,
  confirmAgentRun,
  deleteSkill,
  exportDeepResearchReport,
  fetchActiveDeepResearchRuns,
  fetchDeepResearchSession,
  fetchSkills,
  streamAgentRun,
  streamDeepAgentRun,
  streamDeepAgentRunEvents,
} from '../api/client'
import type { DeepResearchEvidence, DeepResearchTurn } from '../api/client'
import type { AgentEvent, AgentRunMode, AgentStep, BudgetSummary, SkillEntry } from '../types'
import {
  hasDeepSession,
  prepareFollowUpHistory,
  resolveDeepSessionId,
} from './deepSessionState'

const AGENT_META: Record<string, { icon: string; color: string; desc: string }> = {
  ResearchAgent:   { icon: '🔍', color: 'blue',   desc: '知识库检索' },
  AnalysisAgent:   { icon: '📊', color: 'purple', desc: '深度分析' },
  WritingAgent:    { icon: '✍️', color: 'green',  desc: '报告撰写' },
  // DeepResearch 模式专用
  BriefWriter:     { icon: '📝', color: 'amber',  desc: '研究简报' },
  DraftWriter:     { icon: '📄', color: 'amber',  desc: '报告初稿' },
  Supervisor:      { icon: '🧭', color: 'cyan',   desc: '监督降噪' },
  SubResearcher:   { icon: '🔬', color: 'blue',   desc: '并行子研究' },
  FinalWriter:     { icon: '✨', color: 'green',  desc: '最终报告' },
}

const COLOR_CLASSES: Record<string, string> = {
  blue:   'agent-card agent-card-blue bg-blue-900/30 border-blue-700 text-blue-300',
  purple: 'agent-card agent-card-purple bg-purple-900/30 border-purple-700 text-purple-300',
  green:  'agent-card agent-card-green bg-green-900/30 border-green-700 text-green-300',
  amber:  'agent-card agent-card-amber bg-amber-900/30 border-amber-700 text-amber-300',
  cyan:   'agent-card agent-card-cyan bg-cyan-900/30 border-cyan-700 text-cyan-300',
}

interface HitlState {
  runId: string
  steps: AgentStep[]
}

interface CollabEvent {
  from_agent: string
  to_agent: string
  topic: string
  reason: string
}

interface IterationInfo {
  iter: number
  max: number
}

interface CritiqueEvent {
  author: string
  concern: string
  iteration: number
}

interface EvalScore {
  comprehensive: number
  accuracy: number
  coherence: number
  average: number
  reason: string
  iteration: number
}

interface DraftSnapshot {
  content: string
  iteration: number
  avg_score: number | null
}

type ResearchSource = DeepResearchEvidence

interface AgentPanelProps {
  fixedMode?: AgentRunMode
  deepSessionId?: string | null
  deepSessionSelectionKey?: number
  onDeepSessionSaved?: (sessionId: string) => void
  onDeepNewSession?: () => void
  onRunningChange?: (running: boolean) => void
}

export default function AgentPanel({
  fixedMode,
  deepSessionId = null,
  deepSessionSelectionKey = 0,
  onDeepSessionSaved,
  onDeepNewSession,
  onRunningChange,
}: AgentPanelProps) {
  const [task, setTask]                   = useState('')
  const [mode, setMode]                   = useState<AgentRunMode>(fixedMode ?? 'quick')
  const [running, setRunning]             = useState(false)
  const [steps, setSteps]                 = useState<AgentStep[]>([])
  const [result, setResult]               = useState('')
  const [error, setError]                 = useState('')
  const [budget, setBudget]               = useState<BudgetSummary | null>(null)
  const [relevantSkills, setRelevantSkills] = useState<{ name: string; description: string }[]>([])
  const [learnedSkills, setLearnedSkills]   = useState<string[]>([])
  const [allSkills, setAllSkills]           = useState<SkillEntry[]>([])
  const [showLibrary, setShowLibrary]       = useState(false)
  // HITL
  const [hitl, setHitl]                   = useState<HitlState | null>(null)
  const [confirming, setConfirming]        = useState(false)
  // Sub-agent live tool calls: agentName → label[]
  const [agentTools, setAgentTools]        = useState<Record<string, string[]>>({})
  // Inter-agent collaboration events (quick mode)
  const [collabEvents, setCollabEvents]    = useState<CollabEvent[]>([])
  // DeepResearch mode telemetry
  const [iteration, setIteration]          = useState<IterationInfo | null>(null)
  const [phaseStatus, setPhaseStatus]      = useState<{ phase: string; label: string } | null>(null)
  const [researchSources, setResearchSources] = useState<ResearchSource[]>([])
  const [critiques, setCritiques]          = useState<CritiqueEvent[]>([])
  const [evalScores, setEvalScores]        = useState<EvalScore[]>([])
  const [brief, setBrief]                  = useState('')
  const [drafts, setDrafts]                = useState<DraftSnapshot[]>([])
  const [timelineExpanded, setTimelineExpanded] = useState(true)
  const [deepHistory, setDeepHistory]      = useState<DeepResearchTurn[]>([])
  const [deepHistorySessionId, setDeepHistorySessionId] = useState(deepSessionId ?? '')
  const [currentQuestion, setCurrentQuestion] = useState('')
  const [followUp, setFollowUp]            = useState('')
  const [deepRunId, setDeepRunId]          = useState('')
  const [reportTitle, setReportTitle]      = useState('深度研究报告')
  const [exporting, setExporting]          = useState<'md' | 'pdf' | null>(null)
  const [citationValidation, setCitationValidation] = useState<{
    valid: boolean
    issueCount: number
    evidenceCount: number
    sanitized: boolean
  } | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const loadedDeepSessionRef = useRef(deepSessionId ?? '')
  const appliedSelectionKeyRef = useRef(deepSessionSelectionKey)
  const reconnectAttemptedRef = useRef(false)
  const applyAgentEventRef = useRef<(event: AgentEvent) => void>(() => {})
  const onDeepSessionSavedRef = useRef(onDeepSessionSaved)
  onDeepSessionSavedRef.current = onDeepSessionSaved

  useEffect(() => {
    fetchSkills().then((r) => setAllSkills(r.skills)).catch(() => {})
  }, [])

  useEffect(() => {
    onRunningChange?.(running)
  }, [onRunningChange, running])

  useEffect(() => {
    if (fixedMode !== 'deep' || running) return
    const explicitSelection = appliedSelectionKeyRef.current !== deepSessionSelectionKey
    appliedSelectionKeyRef.current = deepSessionSelectionKey

    if (!deepSessionId) {
      if (!explicitSelection) return
      loadedDeepSessionRef.current = ''
      setDeepHistorySessionId('')
      setTask('')
      setSteps([])
      setResult('')
      setError('')
      setBudget(null)
      setRelevantSkills([])
      setLearnedSkills([])
      setAgentTools({})
      setIteration(null)
      setPhaseStatus(null)
      setResearchSources([])
      setCritiques([])
      setEvalScores([])
      setBrief('')
      setDrafts([])
      setTimelineExpanded(true)
      setDeepHistory([])
      setCurrentQuestion('')
      setFollowUp('')
      setDeepRunId('')
      setReportTitle('深度研究报告')
      setCitationValidation(null)
      return
    }

    if (loadedDeepSessionRef.current === deepSessionId && !explicitSelection) return
    let cancelled = false
    fetchDeepResearchSession(deepSessionId)
      .then((session) => {
        if (cancelled) return
        const latestTurn = session.turns[session.turns.length - 1]
        loadedDeepSessionRef.current = session.id
        setDeepHistorySessionId(session.id)
        setTask('')
        setSteps([])
        setResult(latestTurn?.answer ?? '')
        setError('')
        setBudget(null)
        setRelevantSkills([])
        setLearnedSkills([])
        setAgentTools({})
        setIteration(null)
        setPhaseStatus(null)
        setResearchSources(session.evidence ?? [])
        setCritiques([])
        setEvalScores([])
        setBrief('')
        setDrafts([])
        setTimelineExpanded(false)
        setDeepHistory(session.turns)
        setCurrentQuestion(latestTurn?.question ?? '')
        setFollowUp('')
        setDeepRunId(session.run_id)
        setReportTitle(session.title)
        setCitationValidation(null)
      })
      .catch((err) => {
        if (!cancelled) setError(`加载研究记录失败：${String(err)}`)
      })
    return () => { cancelled = true }
  }, [deepSessionId, deepSessionSelectionKey, fixedMode, running])

  const applyAgentEvent = (event: AgentEvent) => {
    if (event.type === 'skills') {
      setRelevantSkills(event.skills)
    } else if (event.type === 'plan') {
      setSteps(event.steps)
    } else if (event.type === 'hitl_confirm') {
      setHitl({ runId: event.run_id, steps: event.steps })
    } else if (event.type === 'agent_start') {
      setHitl(null)
      setSteps((prev) => {
        const exists = prev.some((step) => step.agent === event.agent)
        if (!exists) {
          return [...prev, { agent: event.agent, task: event.task, status: 'running' }]
        }
        return prev.map((step) => (
          step.agent === event.agent
            ? { ...step, status: 'running', task: event.task }
            : step
        ))
      })
    } else if (event.type === 'sub_agent_tool') {
      setAgentTools((prev) => ({
        ...prev,
        [event.agent]: [...(prev[event.agent] ?? []), event.label],
      }))
    } else if (event.type === 'collaboration') {
      setCollabEvents((prev) => [...prev, {
        from_agent: event.from_agent,
        to_agent: event.to_agent,
        topic: event.topic,
        reason: event.reason,
      }])
    } else if (event.type === 'agent_done') {
      setSteps((prev) => prev.map((step) => (
        step.agent === event.agent
          ? { ...step, status: 'done', summary: event.summary, stop_reason: event.stop_reason }
          : step
      )))
    } else if (event.type === 'iteration') {
      setIteration({ iter: event.iter, max: event.max })
    } else if (event.type === 'phase_status') {
      setPhaseStatus({ phase: event.phase, label: event.label })
    } else if (event.type === 'research_source') {
      const source: ResearchSource = {
        source_id: event.source_id,
        query: event.query,
        title: event.title,
        url: event.url,
        snippet: event.snippet,
        status: event.status,
        published_at: event.published_at,
        source_type: event.source_type,
        authority_score: event.authority_score,
        freshness_score: event.freshness_score,
      }
      setResearchSources((prev) => {
        const index = prev.findIndex((item) => item.url === source.url)
        if (index < 0) return [...prev, source]
        const next = [...prev]
        next[index] = source
        return next
      })
    } else if (event.type === 'run_attached') {
      setDeepRunId(event.run_id)
      setDeepHistorySessionId(event.session_id)
      loadedDeepSessionRef.current = event.session_id
      setCurrentQuestion(event.task)
      setReportTitle((title) => title === '深度研究报告' ? event.task : title)
      onDeepSessionSaved?.(event.session_id)
    } else if (event.type === 'run_started' || event.type === 'run_resumed') {
      setDeepRunId(event.run_id)
    } else if (event.type === 'report_replace') {
      setResult(event.content)
    } else if (event.type === 'citation_validation') {
      setCitationValidation({
        valid: event.valid,
        issueCount: event.issues.length,
        evidenceCount: event.evidence_count,
        sanitized: Boolean(event.sanitized),
      })
    } else if (event.type === 'research_state') {
      setBudget(event.budget)
    } else if (event.type === 'research_brief') {
      setBrief(event.content)
    } else if (event.type === 'draft_update') {
      setDrafts((prev) => [
        ...prev,
        { content: event.content, iteration: event.iteration, avg_score: event.avg_score },
      ])
    } else if (event.type === 'eval_score') {
      setEvalScores((prev) => [...prev, {
        comprehensive: event.comprehensive,
        accuracy: event.accuracy,
        coherence: event.coherence,
        average: event.average,
        reason: event.reason,
        iteration: event.iteration,
      }])
    } else if (event.type === 'critique') {
      setCritiques((prev) => [...prev, {
        author: event.author,
        concern: event.concern,
        iteration: event.iteration,
      }])
    } else if (event.type === 'text') {
      setResult((previous) => previous + event.content)
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    } else if (event.type === 'harness') {
      setBudget(event.budget)
    } else if (event.type === 'skill_learned') {
      setLearnedSkills(event.names)
      fetchSkills().then((response) => setAllSkills(response.skills)).catch(() => {})
    } else if (event.type === 'error') {
      setError(event.message)
    } else if (event.type === 'done') {
      setPhaseStatus(null)
    }
  }
  applyAgentEventRef.current = applyAgentEvent

  useEffect(() => {
    if (fixedMode !== 'deep' || reconnectAttemptedRef.current) return
    reconnectAttemptedRef.current = true
    let disposed = false
    const controller = new AbortController()

    const reconnect = async () => {
      try {
        const activeRuns = await fetchActiveDeepResearchRuns()
        const active = activeRuns[0]
        if (!active || disposed) return

        abortControllerRef.current = controller
        setRunning(true)
        setTimelineExpanded(true)
        setError('')
        setSteps([])
        setResult('')
        setBudget(null)
        setRelevantSkills([])
        setLearnedSkills([])
        setAgentTools({})
        setCollabEvents([])
        setIteration(null)
        setPhaseStatus({ phase: 'reconnecting', label: '正在恢复研究进度…' })
        setResearchSources([])
        setCritiques([])
        setEvalScores([])
        setBrief('')
        setDrafts([])
        setCitationValidation(null)
        setDeepRunId(active.run_id)
        setDeepHistorySessionId(active.session_id)
        loadedDeepSessionRef.current = active.session_id
        setCurrentQuestion(active.task)
        setReportTitle(active.task)
        onDeepSessionSavedRef.current?.(active.session_id)

        try {
          const session = await fetchDeepResearchSession(active.session_id)
          if (!disposed) {
            setDeepHistory(session.turns)
            setResearchSources(session.evidence ?? [])
            setReportTitle(session.title)
          }
        } catch {
          // The run metadata already contains enough information to reconnect.
        }

        for await (const event of streamDeepAgentRunEvents(
          active.run_id,
          0,
          controller.signal,
        )) {
          if (disposed) return
          applyAgentEventRef.current(event)
        }

        const session = await fetchDeepResearchSession(active.session_id)
        if (!disposed) {
          const latestTurn = session.turns[session.turns.length - 1]
          setDeepHistory(session.turns)
          setResult(latestTurn?.answer ?? '')
          setResearchSources(session.evidence ?? [])
          setCurrentQuestion(latestTurn?.question ?? active.task)
          setDeepRunId(session.run_id)
          setReportTitle(session.title)
          onDeepSessionSavedRef.current?.(session.id)
        }
      } catch (err) {
        if (!disposed && !(err instanceof DOMException && err.name === 'AbortError')) {
          setError(`恢复研究连接失败：${String(err)}`)
        }
      } finally {
        if (!disposed) {
          setRunning(false)
          setPhaseStatus(null)
          abortControllerRef.current = null
        }
      }
    }

    void reconnect()
    return () => {
      disposed = true
      controller.abort()
    }
  }, [fixedMode])

  const run = async (taskOverride?: string, continueConversation = false) => {
    const t = (taskOverride ?? task).trim()
    if (!t || running) return
    const selectedMode = mode
    const sessionIdForRun = selectedMode === 'deep'
      ? resolveDeepSessionId(
          deepHistorySessionId,
          deepSessionId,
          crypto.randomUUID(),
        )
      : ''
    let conversationHistory = deepHistory
    if (selectedMode === 'deep' && continueConversation) {
      conversationHistory = prepareFollowUpHistory(
        deepHistory,
        currentQuestion,
        result,
      )
      // The persisted session is authoritative when a refresh completed after
      // the local UI rendered. This prevents a follow-up from losing turn one.
      try {
        const stored = await fetchDeepResearchSession(sessionIdForRun)
        if (stored.turns.length >= conversationHistory.length) {
          conversationHistory = prepareFollowUpHistory(
            stored.turns,
            currentQuestion,
            result,
          )
        }
      } catch {
        // The visible completed turn above is still sufficient context.
      }
      setDeepHistory(conversationHistory)
    }
    const history = selectedMode === 'deep' && continueConversation
      ? conversationHistory.slice(-3)
      : []
    if (selectedMode === 'deep' && !continueConversation) {
      setDeepHistory([])
      setReportTitle(t)
    }
    if (selectedMode === 'deep') {
      setCurrentQuestion(t)
      setDeepHistorySessionId(sessionIdForRun)
      loadedDeepSessionRef.current = sessionIdForRun
    }
    setRunning(true)
    setSteps([])
    setResult('')
    setError('')
    setBudget(null)
    setRelevantSkills([])
    setLearnedSkills([])
    setHitl(null)
    setAgentTools({})
    setCollabEvents([])
    setIteration(null)
    setPhaseStatus(null)
    setResearchSources([])
    setCritiques([])
    setEvalScores([])
    setBrief('')
    setDrafts([])
    setTimelineExpanded(true)
    setCitationValidation(null)
    if (selectedMode === 'deep') setDeepRunId('')

    const controller = selectedMode === 'deep' ? new AbortController() : null
    abortControllerRef.current = controller
    const stream = selectedMode === 'deep'
      ? streamDeepAgentRun(t, history, sessionIdForRun, controller?.signal)
      : streamAgentRun(t)
    try {
      for await (const event of stream) {
        applyAgentEventRef.current(event)
      }
    } catch (err) {
      setError(err instanceof DOMException && err.name === 'AbortError' ? '研究已取消' : String(err))
    } finally {
      if (selectedMode === 'deep') {
        try {
          const session = await fetchDeepResearchSession(sessionIdForRun)
          const latestTurn = session.turns[session.turns.length - 1]
          setDeepHistory(session.turns)
          setResult(latestTurn?.answer ?? '')
          setResearchSources(session.evidence ?? [])
          setCurrentQuestion(latestTurn?.question ?? t)
          setDeepRunId(session.run_id)
          setReportTitle(session.title)
          onDeepSessionSaved?.(sessionIdForRun)
        } catch (historyError) {
          console.warn('[DeepResearch] 加载研究结果失败', historyError)
        }
      }
      if (continueConversation) setFollowUp('')
      if (selectedMode === 'deep') setTimelineExpanded(false)
      setRunning(false)
      setHitl(null)
      abortControllerRef.current = null
    }
  }

  const handleDeepCancel = async () => {
    if (deepRunId) await cancelDeepAgentRun(deepRunId).catch(() => {})
    abortControllerRef.current?.abort()
  }

  const handleExport = async (format: 'md' | 'pdf') => {
    if (!result.trim() || exporting) return
    setExporting(format)
    setError('')
    try {
      const blob = await exportDeepResearchReport(reportTitle, result, format)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      const safeTitle = reportTitle
        .replace(/[\\/:*?"<>|]+/g, '-')
        .replace(/\s+/g, '-')
        .slice(0, 80) || 'deep-research'
      anchor.href = url
      anchor.download = `${safeTitle}.${format}`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(`导出 ${format.toUpperCase()} 失败：${String(err)}`)
    } finally {
      setExporting(null)
    }
  }

  const handleConfirm = async () => {
    if (!hitl) return
    setConfirming(true)
    try {
      await confirmAgentRun(hitl.runId)
    } finally {
      setConfirming(false)
    }
  }

  const handleCancel = () => {
    setHitl(null)
    setRunning(false)
    setError('已取消')
  }

  const handleDeleteSkill = async (skillId: string) => {
    await deleteSkill(skillId).catch(() => {})
    setAllSkills((prev) => prev.filter((s) => s.skill_id !== skillId))
  }

  const handleNewDeepResearch = () => {
    if (running) return
    setTask('')
    setSteps([])
    setResult('')
    setError('')
    setBudget(null)
    setRelevantSkills([])
    setLearnedSkills([])
    setHitl(null)
    setAgentTools({})
    setCollabEvents([])
    setIteration(null)
    setPhaseStatus(null)
    setResearchSources([])
    setCritiques([])
    setEvalScores([])
    setBrief('')
    setDrafts([])
    setTimelineExpanded(true)
    setDeepHistory([])
    setDeepHistorySessionId('')
    loadedDeepSessionRef.current = ''
    setCurrentQuestion('')
    setFollowUp('')
    setDeepRunId('')
    setReportTitle('深度研究报告')
    setCitationValidation(null)
    onDeepNewSession?.()
  }

  const latestStoredTurn = deepHistory[deepHistory.length - 1]
  const currentTurnIsStored = Boolean(
    latestStoredTurn
    && latestStoredTurn.question === currentQuestion
    && (latestStoredTurn.answer === result || running),
  )
  const previousDeepTurns = currentTurnIsStored
    ? deepHistory.slice(0, -1)
    : deepHistory
  const deepSessionActive = mode === 'deep' && hasDeepSession({
    running,
    result,
    historyLength: deepHistory.length,
    currentQuestion,
    runId: deepRunId,
  })

  return (
    <div className={`relative h-full min-h-0 flex flex-col gap-5 overflow-y-auto scroll-pb-36 ${
      mode === 'deep' ? 'pb-0' : 'pb-4'
    }`}>
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">
            {mode === 'deep' ? '深度研究' : '深度分析'}
          </h2>
          {mode === 'quick' && (
            <p className="mt-1 text-sm text-gray-400">
              Research → Analysis → Writing · Agent 间协作 · HITL 确认
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {mode === 'deep' && running && (
            <button
              onClick={() => void handleDeepCancel()}
              className="rounded-lg border border-red-800 bg-red-900/50 px-3 py-1.5 text-xs text-red-300 transition-colors hover:bg-red-800/70"
            >
              停止研究
            </button>
          )}
          <button
            onClick={() => setShowLibrary(!showLibrary)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 text-gray-400 rounded-lg transition-colors border border-gray-700"
          >
            <span>📚</span>
            <span>技能库 {allSkills.length > 0 && `(${allSkills.length})`}</span>
          </button>
        </div>
      </div>

      {/* Mode switch */}
      {!fixedMode && (
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-lg border border-gray-700 bg-gray-800/60 p-0.5">
          <button
            onClick={() => !running && setMode('quick')}
            disabled={running}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
              mode === 'quick'
                ? 'bg-blue-600 text-white'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            ⚡ Quick · 知识库
          </button>
          <button
            onClick={() => !running && setMode('deep')}
            disabled={running}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
              mode === 'deep'
                ? 'bg-cyan-600 text-white'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            🧬 Deep · 自进化+对抗
          </button>
          </div>
        </div>
      )}

      {/* Skill Library Panel */}
      {showLibrary && (
        <div className="bg-gray-800/60 rounded-xl border border-gray-700 p-4">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-3">已学会的技能</p>
          {allSkills.length === 0 ? (
            <p className="text-xs text-gray-600">暂无技能。完成一次深度分析后，系统会自动提取可复用的技能。</p>
          ) : (
            <div className="space-y-2">
              {allSkills.map((s) => (
                <div key={s.skill_id} className="flex items-center justify-between gap-3 py-1.5">
                  <div className="min-w-0">
                    <p className="text-xs text-gray-300 truncate">{s.name}</p>
                    <p className="text-[10px] text-gray-600 mt-0.5">
                      使用 {s.use_count} 次 · {s.tags.join(', ') || '无标签'}
                    </p>
                  </div>
                  <button
                    onClick={() => handleDeleteSkill(s.skill_id)}
                    className="shrink-0 text-[10px] text-gray-600 hover:text-red-400 transition-colors"
                  >
                    删除
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Initial input: DeepResearch moves to the conversation composer after submit. */}
      {(mode !== 'deep' || !deepSessionActive) && (
        <div className="flex flex-col gap-2">
        <textarea
          value={task}
          onChange={(e) => setTask(e.target.value)}
          placeholder={
            mode === 'quick'
              ? '输入需要深度分析的任务,例如:「帮我分析知识库中关于投资理财的所有内容,找出核心规律并写成报告」'
              : '输入你想深入研究的问题…'
          }
          rows={3}
          disabled={running}
          className="w-full bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-sm text-white
            placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none disabled:opacity-50"
          onKeyDown={(e) => { if (e.key === 'Enter' && e.metaKey) void run() }}
        />
        <div className="flex items-center justify-between">
          <p className="text-xs text-gray-600">⌘+Enter 执行 · 当前模式 <span className={mode === 'deep' ? 'text-cyan-400' : 'text-blue-400'}>{mode === 'deep' ? 'Deep' : 'Quick'}</span></p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => void run()}
              disabled={running || !task.trim()}
              className={`px-5 py-2 ${
                mode === 'deep'
                  ? 'bg-cyan-600 hover:bg-cyan-500'
                  : 'bg-blue-600 hover:bg-blue-500'
              } disabled:opacity-40 disabled:cursor-not-allowed
                text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2`}
            >
              {running && !hitl && (
                <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
              )}
              {running && !hitl ? '研究中…' : mode === 'deep' ? '开始深度研究' : '开始分析'}
            </button>
          </div>
        </div>
        </div>
      )}

      {/* Relevant skills context */}
      {relevantSkills.length > 0 && (
        <div className="bg-indigo-900/20 border border-indigo-800 rounded-xl px-4 py-3">
          <p className="text-xs text-indigo-400 font-medium mb-1.5">🧠 调用相关技能</p>
          <div className="space-y-1">
            {relevantSkills.map((s, i) => (
              <p key={i} className="text-xs text-indigo-300/80">• {s.name}</p>
            ))}
          </div>
        </div>
      )}

      {/* ── HITL Confirmation Card (quick 模式专属) ── */}
      {mode === 'quick' && hitl && (
        <div className="bg-amber-900/20 border border-amber-700 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-base">🔐</span>
            <p className="text-sm font-semibold text-amber-300">确认执行计划</p>
          </div>
          <p className="text-xs text-amber-400/70 mb-3">
            Agent 已完成规划，请确认以下执行方案后继续。
          </p>
          <div className="space-y-2 mb-4">
            {hitl.steps.map((s, i) => {
              const meta = AGENT_META[s.agent] ?? { icon: '🤖', desc: s.agent }
              return (
                <div key={i} className="flex items-start gap-2 text-xs text-amber-200/80">
                  <span className="shrink-0 mt-0.5">{meta.icon}</span>
                  <div>
                    <span className="font-medium">{s.agent}</span>
                    <span className="text-amber-400/60 ml-1">—</span>
                    <span className="ml-1 opacity-80">{s.task}</span>
                  </div>
                </div>
              )
            })}
          </div>
          <div className="flex gap-2 justify-end">
            <button
              onClick={handleCancel}
              className="px-4 py-1.5 text-xs text-gray-400 hover:text-white bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
            >
              取消
            </button>
            <button
              onClick={handleConfirm}
              disabled={confirming}
              className="px-4 py-1.5 text-xs text-white bg-amber-600 hover:bg-amber-500 disabled:opacity-50 rounded-lg transition-colors flex items-center gap-1.5"
            >
              {confirming && (
                <span className="w-3 h-3 border border-white border-t-transparent rounded-full animate-spin" />
              )}
              确认执行
            </button>
          </div>
        </div>
      )}

      {/* Previous turns come first so follow-ups read as a chronological conversation. */}
      {mode === 'deep' && previousDeepTurns.length > 0 && (
        <section
          aria-label="历史研究记录"
          className="rounded-xl border border-gray-700 bg-gray-800/20 px-4 py-3"
        >
          <div className="mb-2 flex items-center justify-between gap-3">
            <p className="text-xs font-medium text-gray-300">
              研究会话记录
            </p>
            <span className="text-[10px] text-gray-500">
              已完成 {previousDeepTurns.length} 轮
            </span>
          </div>
          <div className="space-y-2">
            {previousDeepTurns.map((turn, index) => (
              <details
                key={`${index}-${turn.question}`}
                open={index === previousDeepTurns.length - 1}
                className="rounded-lg border border-gray-700 bg-gray-800/50 px-3 py-2"
              >
                <summary className="cursor-pointer select-none text-xs font-medium text-gray-300">
                  <span className="mr-2 text-cyan-400">第 {index + 1} 轮</span>
                  {turn.question}
                </summary>
                <div className="prose-custom mt-3 border-t border-gray-700 pt-3 text-sm leading-relaxed">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: ({ ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
                      table: ({ ...props }) => (
                        <div className="markdown-table-scroll">
                          <table {...props} />
                        </div>
                      ),
                    }}
                  >
                    {turn.answer}
                  </ReactMarkdown>
                </div>
              </details>
            ))}
          </div>
        </section>
      )}

      {mode === 'deep' && currentQuestion && (
        <section
          aria-label="当前研究问题"
          className="deep-current-question rounded-xl border border-cyan-800/60 bg-cyan-900/20 px-4 py-3"
        >
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-300">
            你的问题
          </p>
          <p className="text-sm font-medium leading-relaxed text-cyan-100">
            {currentQuestion}
          </p>
        </section>
      )}

      {/* Execution Timeline */}
      {steps.length > 0 && (
        <section className="deep-execution-panel space-y-2" aria-label="执行轨迹">
          <div className="deep-section-header flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2.5">
              <p className="deep-section-title text-xs font-medium uppercase tracking-wide text-gray-500">
                执行轨迹
              </p>
              <span className="deep-section-count rounded-full border border-gray-700/70 bg-gray-800/40 px-2 py-0.5 text-[10px] text-gray-500">
                {steps.filter((step) => step.status === 'done').length} / {steps.length} 已完成
              </span>
            </div>
            <button
              type="button"
              className="deep-collapse-button inline-flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors"
              onClick={() => setTimelineExpanded((expanded) => !expanded)}
              aria-expanded={timelineExpanded}
              aria-controls="deep-execution-timeline"
            >
              <svg
                viewBox="0 0 20 20"
                fill="none"
                aria-hidden="true"
                className={`deep-collapse-chevron h-3.5 w-3.5 ${timelineExpanded ? 'is-open' : ''}`}
              >
                <path d="m5.75 7.5 4.25 4.25 4.25-4.25" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {timelineExpanded ? '全部收起' : '全部展开'}
            </button>
          </div>
          {timelineExpanded && (
            <div id="deep-execution-timeline" className="flex flex-col gap-2">
              {steps.map((step, i) => {
              const meta = AGENT_META[step.agent] ?? { icon: '🤖', color: 'blue', desc: step.agent }
              const colorCls = COLOR_CLASSES[meta.color] ?? COLOR_CLASSES.blue
              const toolCalls = agentTools[step.agent] ?? []

              // Inject collaboration cards before the AnalysisAgent step
              const collabBefore = step.agent === 'AnalysisAgent' && collabEvents.length > 0
                ? collabEvents
                : []

              return (
                <div key={i} className="flex flex-col gap-2">
                  {/* Collaboration connector cards injected before AnalysisAgent */}
                  {collabBefore.map((ev, ci) => (
                    <div key={`collab-${ci}`} className="relative">
                      <div className="absolute left-4 -top-2 bottom-0 w-px bg-cyan-800/50" />
                      <div className="ml-8 bg-cyan-900/20 border border-cyan-800/60 rounded-xl px-4 py-2.5">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs">🔄</span>
                          <span className="text-[11px] font-semibold text-cyan-300">Agent 间协作请求</span>
                        </div>
                        <div className="flex items-center gap-1.5 text-[11px] text-cyan-200/70">
                          <span className="font-medium">{ev.from_agent}</span>
                          <span className="opacity-50">→</span>
                          <span className="font-medium">{ev.to_agent}</span>
                          <span className="opacity-50 mx-1">·</span>
                          <span>补充检索「{ev.topic}」</span>
                        </div>
                        {ev.reason && (
                          <p className="text-[10px] text-cyan-300/40 mt-0.5 leading-relaxed">
                            原因：{ev.reason}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}

                  {/* Agent execution card */}
                  <div className={`rounded-xl border px-4 py-3 ${colorCls} transition-all`}>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-base">{meta.icon}</span>
                      <span className="text-xs font-semibold">{step.agent}</span>
                      <span className="text-xs opacity-60">— {meta.desc}</span>
                      <div className="ml-auto shrink-0">
                        {step.status === 'pending' && <span className="text-xs opacity-40">等待中</span>}
                        {step.status === 'running' && (
                          <span className="flex items-center gap-1 text-xs">
                            <span className="w-2.5 h-2.5 border border-current border-t-transparent rounded-full animate-spin" />
                            执行中
                          </span>
                        )}
                        {step.status === 'done' && <span className="text-xs">✓ 完成</span>}
                      </div>
                    </div>

                    <p className="text-xs opacity-70 truncate">{step.task}</p>

                    {/* Live tool call chips */}
                    {toolCalls.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-2">
                        {toolCalls.map((label, j) => (
                          <span
                            key={j}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] bg-current/10 border border-current/20 opacity-80"
                          >
                            <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
                            {label}
                          </span>
                        ))}
                      </div>
                    )}

                    {step.agent === 'SubResearcher' && researchSources.length > 0 && (
                      <details className="mt-3 border-t border-current/20 pt-2.5">
                        <summary className="cursor-pointer select-none text-[10px] font-semibold uppercase tracking-wide opacity-70 hover:opacity-100">
                          已检索资料 · {researchSources.length}
                          <span className="ml-2 font-normal normal-case opacity-60">点击展开 / 收起</span>
                        </summary>
                        <div className="mt-2 space-y-2">
                          {researchSources.map((source) => (
                          <div
                            key={`${source.query}-${source.url}`}
                            className="rounded-lg bg-gray-950/25 border border-current/15 px-3 py-2"
                          >
                            <div className="flex items-start gap-2">
                              <span className={`mt-1 w-1.5 h-1.5 shrink-0 rounded-full ${
                                source.status === 'summarized' ? 'bg-green-400' : 'bg-cyan-400 animate-pulse'
                              }`} />
                              <div className="min-w-0 flex-1">
                                <a
                                  href={source.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="block text-[11px] font-medium text-cyan-200 hover:text-cyan-100 hover:underline truncate"
                                >
                                  {source.title || source.url}
                                </a>
                                <p className="text-[10px] opacity-45 truncate mt-0.5">
                                  查询：{source.query}
                                </p>
                                {source.snippet && (
                                  <p className="text-[10px] opacity-60 leading-relaxed mt-1 line-clamp-2">
                                    {source.snippet}
                                  </p>
                                )}
                              </div>
                              <span className="text-[9px] opacity-40 shrink-0">
                                {source.status === 'summarized' ? '已摘要' : '已发现'}
                              </span>
                            </div>
                          </div>
                          ))}
                        </div>
                      </details>
                    )}

                    {step.status === 'done' && step.summary && (
                      <p className="text-xs opacity-60 mt-1.5 line-clamp-2 border-t border-current/20 pt-1.5">
                        {step.summary}
                      </p>
                    )}
                    {step.status === 'done' && step.stop_reason && (
                      <p className="text-[10px] opacity-40 mt-1 italic">
                        停止原因：{step.stop_reason}
                      </p>
                    )}
                  </div>
                </div>
              )
              })}
            </div>
          )}
        </section>
      )}

      {/* DeepResearch telemetry: iteration / eval_score / critique */}
      {mode === 'deep' && (iteration || evalScores.length > 0 || critiques.length > 0 || brief || drafts.length > 0) && (
        <div className="space-y-3">
          {/* Research brief */}
          {brief && (
            <details className="deep-brief-card bg-amber-900/15 border border-amber-800/50 rounded-xl px-4 py-2.5">
              <summary className="deep-brief-title text-xs text-amber-300 cursor-pointer flex items-center gap-1.5">
                <span>📝</span> 研究简报 <span className="text-amber-400/50">({brief.length} 字符)</span>
              </summary>
              <p className="deep-brief-body text-xs text-amber-200/70 mt-2 leading-relaxed whitespace-pre-wrap">
                {brief}
              </p>
            </details>
          )}

          {/* Draft snapshots */}
          {drafts.length > 0 && (
            <details className="deep-telemetry-card bg-gray-800/40 border border-gray-700 rounded-xl px-4 py-2.5">
              <summary className="text-xs text-gray-400 cursor-pointer flex items-center gap-1.5">
                <span>📄</span> 报告草稿快照 ({drafts.length})
                {drafts.length > 0 && drafts[drafts.length - 1].avg_score !== null && (
                  <span className="text-cyan-400 ml-1">
                    最新均分 {drafts[drafts.length - 1].avg_score}
                  </span>
                )}
              </summary>
              <div className="space-y-2 mt-2">
                {drafts.map((d, i) => (
                  <div key={i} className="text-xs text-gray-400 border-l-2 border-gray-700 pl-3">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-gray-500">
                        {d.iteration === 0 ? '初稿' : `第 ${d.iteration} 轮精修`}
                      </span>
                      {d.avg_score !== null && (
                        <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                          d.avg_score >= 7 ? 'bg-green-900/40 text-green-300'
                          : d.avg_score >= 5 ? 'bg-amber-900/40 text-amber-300'
                          : 'bg-red-900/40 text-red-300'
                        }`}>
                          均分 {d.avg_score}
                        </span>
                      )}
                    </div>
                    <p className="line-clamp-3 text-gray-500 leading-relaxed">{d.content}</p>
                  </div>
                ))}
              </div>
            </details>
          )}

          {/* Iteration progress */}
          {iteration && (
            <div className="deep-iteration-card bg-cyan-900/15 border border-cyan-800/50 rounded-xl px-4 py-2.5">
              <div className="flex items-center gap-3">
                <span className="text-base">🔁</span>
                <span className="text-xs font-semibold text-cyan-300">
                  迭代 {iteration.iter} / {iteration.max}
                </span>
                <div className="flex-1 h-1.5 bg-cyan-900/40 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-cyan-400 transition-all"
                    style={{ width: `${(iteration.iter / iteration.max) * 100}%` }}
                  />
                </div>
              </div>
              {phaseStatus && (
                <div className="mt-2 ml-8 flex items-center gap-2 text-[11px] text-cyan-200/70">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
                  <span>{phaseStatus.label}</span>
                </div>
              )}
            </div>
          )}

          {/* Eval scores timeline */}
          {evalScores.length > 0 && (
            <div className="deep-telemetry-card deep-eval-card bg-gray-800/40 border border-gray-700 rounded-xl px-4 py-3">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-2 flex items-center gap-1.5">
                <span>⚖️</span> LLM-as-Judge 三维评分
              </p>
              <div className="space-y-2">
                {evalScores.map((s, i) => (
                  <div key={i} className="flex items-center gap-3 text-xs">
                    <span className="text-gray-500 w-10 shrink-0">#{s.iteration}</span>
                    <div className="flex-1 grid grid-cols-3 gap-2">
                      <div className="flex items-center gap-1.5">
                        <span className="text-gray-400 w-14">全面性</span>
                        <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                          <div
                            className={`h-full ${s.comprehensive >= 7 ? 'bg-green-400' : s.comprehensive >= 5 ? 'bg-amber-400' : 'bg-red-400'}`}
                            style={{ width: `${s.comprehensive * 10}%` }}
                          />
                        </div>
                        <span className="text-gray-300 w-6 text-right">{s.comprehensive}</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="text-gray-400 w-14">准确性</span>
                        <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                          <div
                            className={`h-full ${s.accuracy >= 7 ? 'bg-green-400' : s.accuracy >= 5 ? 'bg-amber-400' : 'bg-red-400'}`}
                            style={{ width: `${s.accuracy * 10}%` }}
                          />
                        </div>
                        <span className="text-gray-300 w-6 text-right">{s.accuracy}</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="text-gray-400 w-14">一致性</span>
                        <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                          <div
                            className={`h-full ${s.coherence >= 7 ? 'bg-green-400' : s.coherence >= 5 ? 'bg-amber-400' : 'bg-red-400'}`}
                            style={{ width: `${s.coherence * 10}%` }}
                          />
                        </div>
                        <span className="text-gray-300 w-6 text-right">{s.coherence}</span>
                      </div>
                    </div>
                    <span className="text-cyan-300 font-medium w-12 text-right">均 {s.average}</span>
                  </div>
                ))}
              </div>
              {evalScores.length > 0 && (
                <p className="text-[11px] text-gray-500 mt-2 leading-relaxed">
                  <span className="text-gray-400">最近评分依据:</span>{' '}
                  {evalScores[evalScores.length - 1].reason}
                </p>
              )}
            </div>
          )}

          {/* Red Team critiques */}
          {critiques.length > 0 && (
            <div className="deep-red-team-card bg-rose-900/15 border border-rose-800/50 rounded-xl px-4 py-3">
              <p className="deep-red-team-title text-xs text-rose-400 uppercase tracking-wide mb-2 flex items-center gap-1.5">
                <span>🗡️</span> Red Team 对抗反馈 ({critiques.length})
              </p>
              <div className="space-y-2">
                {critiques.map((c, i) => (
                  <div key={i} className="deep-red-team-item text-xs text-rose-200/80 leading-relaxed">
                    <span className="deep-red-team-index text-rose-400 font-medium">#{c.iteration} </span>
                    {c.concern}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {citationValidation && (
        <div className={`deep-citation-card rounded-xl border px-4 py-2.5 text-xs ${
          citationValidation.valid
            ? 'bg-green-900/20 border-green-800 text-green-300'
            : 'bg-amber-900/20 border-amber-800 text-amber-300'
        }`}>
          引用校验：{citationValidation.valid ? '通过' : `发现 ${citationValidation.issueCount} 个问题`}
          {' · '}证据 {citationValidation.evidenceCount} 条
          {citationValidation.sanitized && ' · 已移除未验证链接'}
        </div>
      )}

      {/* Harness telemetry */}
      {budget && (
        <div className="deep-budget-card bg-gray-800/40 border border-gray-700 rounded-xl px-4 py-2.5 flex items-center gap-4 flex-wrap">
          <span className="text-[10px] text-gray-500 uppercase tracking-wide font-medium">Harness</span>
          <span className="text-xs text-gray-400">输入 {budget.input_tokens.toLocaleString()} tokens</span>
          <span className="text-xs text-gray-400">输出 {budget.output_tokens.toLocaleString()} tokens</span>
          <span className="text-xs text-gray-400">工具调用 {budget.tool_calls} 次</span>
          {budget.cost_usd !== undefined && (
            <span className="text-xs text-gray-400">估算费用 ${budget.cost_usd.toFixed(4)}</span>
          )}
        </div>
      )}

      {/* Newly learned skills */}
      {learnedSkills.length > 0 && (
        <div className="deep-skill-card bg-green-900/20 border border-green-800 rounded-xl px-4 py-2.5">
          <p className="text-xs text-green-400">
            ✨ 学习了 {learnedSkills.length} 个新技能：{learnedSkills.join('、')}
          </p>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-xl bg-red-900/20 border border-red-800 px-4 py-3 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Result */}
      {result && (
        <div className={mode === 'deep' ? 'shrink-0' : 'flex-1 min-h-0'}>
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs text-gray-500 uppercase tracking-wide">
                {mode === 'deep' ? '深度研究报告' : '综合报告'}
              </p>
            </div>
            {mode === 'deep' && !running && (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => void handleExport('md')}
                  disabled={exporting !== null}
                  className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 transition-colors hover:border-cyan-700 hover:text-cyan-300 disabled:opacity-40"
                >
                  {exporting === 'md' ? '导出中…' : '导出 Markdown'}
                </button>
                <button
                  onClick={() => void handleExport('pdf')}
                  disabled={exporting !== null}
                  className="rounded-lg border border-cyan-800 bg-cyan-950/30 px-3 py-1.5 text-xs text-cyan-300 transition-colors hover:bg-cyan-900/40 disabled:opacity-40"
                >
                  {exporting === 'pdf' ? '生成 PDF…' : '导出 PDF'}
                </button>
              </div>
            )}
          </div>
          <div className="bg-gray-800/50 rounded-xl border border-gray-700 px-5 py-4">
            <div className="prose-custom text-sm leading-relaxed">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
                  table: ({ ...props }) => (
                    <div className="markdown-table-scroll">
                      <table {...props} />
                    </div>
                  ),
                }}
              >
                {result}
              </ReactMarkdown>
            </div>
            <div ref={bottomRef} />
          </div>
        </div>
      )}

      {/* DeepResearch composer remains pinned to the active scroll viewport. */}
      {mode === 'deep' && deepSessionActive && (
        <div
          className="deep-research-composer sticky bottom-0 z-30 mt-auto shrink-0 rounded-2xl border px-2.5 py-2"
        >
          <div className="flex items-center gap-1.5">
            <button
              onClick={handleNewDeepResearch}
              disabled={running}
              aria-label="新建研究"
              title="新建研究"
              className="deep-composer-new flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-gray-400 transition-all duration-200 hover:text-cyan-300 disabled:cursor-not-allowed disabled:opacity-30"
            >
              <svg aria-hidden="true" viewBox="0 0 24 24" className="h-[18px] w-[18px] fill-none stroke-current" strokeWidth="1.8">
                <path d="M12 5v14M5 12h14" strokeLinecap="round" />
              </svg>
            </button>
            <textarea
              value={followUp}
              onChange={(e) => setFollowUp(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key === 'Enter'
                  && !e.shiftKey
                  && !e.nativeEvent.isComposing
                  && followUp.trim()
                ) {
                  e.preventDefault()
                  void run(followUp, true)
                }
              }}
              rows={1}
              disabled={running}
              aria-label="继续深研的问题"
              placeholder={running ? '正在研究…' : '继续追问…'}
              className="deep-followup-input h-10 min-h-10 flex-1 resize-none overflow-y-auto bg-transparent px-2.5 py-2.5 text-sm leading-5 text-white focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
            />
            <button
              onClick={() => void run(followUp, true)}
              disabled={running || !followUp.trim()}
              aria-label={running ? '研究中' : '发送追问'}
              title={running ? '研究中' : '发送追问'}
              className="deep-composer-send flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-25"
            >
              {running ? (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              ) : (
                <svg aria-hidden="true" viewBox="0 0 24 24" className="h-[18px] w-[18px] fill-none stroke-current" strokeWidth="2">
                  <path d="M12 19V5m0 0-6 6m6-6 6 6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          </div>
        </div>
      )}

      {mode === 'quick' && !steps.length && !result && !running && !error && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-4xl mb-3">🤖</p>
            <p className="text-sm text-gray-500">
              输入复杂任务,多个 Agent 顺序协作完成深度分析
            </p>
            <div className="flex justify-center gap-4 mt-4">
              {['ResearchAgent', 'AnalysisAgent', 'WritingAgent'].map((name) => {
                const meta = AGENT_META[name] ?? { icon: '🤖', desc: name }
                return (
                  <div key={name} className="flex items-center gap-1.5 text-xs text-gray-600">
                    <span>{meta.icon}</span>
                    <span>{name}</span>
                  </div>
                )
              })}
            </div>
            <p className="text-xs text-gray-700 mt-3">
              分析过程中如发现知识缺口,Agent 间可互相请求补充研究
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
