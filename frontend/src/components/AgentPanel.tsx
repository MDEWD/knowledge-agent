import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { confirmAgentRun, deleteSkill, fetchSkills, streamAgentRun } from '../api/client'
import type { AgentStep, BudgetSummary, SkillEntry } from '../types'

const AGENT_META: Record<string, { icon: string; color: string; desc: string }> = {
  ResearchAgent: { icon: '🔍', color: 'blue',   desc: '知识库检索' },
  AnalysisAgent: { icon: '📊', color: 'purple', desc: '深度分析' },
  WritingAgent:  { icon: '✍️', color: 'green',  desc: '报告撰写' },
}

const COLOR_CLASSES: Record<string, string> = {
  blue:   'bg-blue-900/30 border-blue-700 text-blue-300',
  purple: 'bg-purple-900/30 border-purple-700 text-purple-300',
  green:  'bg-green-900/30 border-green-700 text-green-300',
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

export default function AgentPanel() {
  const [task, setTask]                   = useState('')
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
  // Inter-agent collaboration events
  const [collabEvents, setCollabEvents]    = useState<CollabEvent[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetchSkills().then((r) => setAllSkills(r.skills)).catch(() => {})
  }, [])

  const run = async () => {
    const t = task.trim()
    if (!t || running) return
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

    try {
      for await (const event of streamAgentRun(t)) {
        if (event.type === 'skills') {
          setRelevantSkills(event.skills)
        } else if (event.type === 'plan') {
          setSteps(event.steps)
        } else if (event.type === 'hitl_confirm') {
          setHitl({ runId: event.run_id, steps: event.steps })
        } else if (event.type === 'agent_start') {
          setHitl(null)
          setSteps((prev) =>
            prev.map((s) =>
              s.agent === event.agent ? { ...s, status: 'running' } : s,
            ),
          )
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
          setSteps((prev) =>
            prev.map((s) =>
              s.agent === event.agent
                ? { ...s, status: 'done', summary: event.summary, stop_reason: event.stop_reason }
                : s,
            ),
          )
        } else if (event.type === 'text') {
          setResult((r) => r + event.content)
          bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
        } else if (event.type === 'harness') {
          setBudget(event.budget)
        } else if (event.type === 'skill_learned') {
          setLearnedSkills(event.names)
          fetchSkills().then((r) => setAllSkills(r.skills)).catch(() => {})
        } else if (event.type === 'error') {
          setError(event.message)
        }
      }
    } catch (err) {
      setError(String(err))
    } finally {
      setRunning(false)
      setHitl(null)
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

  return (
    <div className="h-full flex flex-col gap-5 overflow-y-auto pb-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white mb-1">深度分析</h2>
          <p className="text-sm text-gray-400">
            Research → Analysis → Writing · Agent 间协作 · HITL 确认
          </p>
        </div>
        <button
          onClick={() => setShowLibrary(!showLibrary)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 text-gray-400 rounded-lg transition-colors border border-gray-700"
        >
          <span>📚</span>
          <span>技能库 {allSkills.length > 0 && `(${allSkills.length})`}</span>
        </button>
      </div>

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

      {/* Input */}
      <div className="flex flex-col gap-2">
        <textarea
          value={task}
          onChange={(e) => setTask(e.target.value)}
          placeholder="输入需要深度分析的任务，例如：「帮我分析知识库中关于投资理财的所有内容，找出核心规律并写成报告」"
          rows={3}
          disabled={running}
          className="w-full bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-sm text-white
            placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none disabled:opacity-50"
          onKeyDown={(e) => { if (e.key === 'Enter' && e.metaKey) run() }}
        />
        <div className="flex items-center justify-between">
          <p className="text-xs text-gray-600">⌘+Enter 执行</p>
          <button
            onClick={run}
            disabled={running || !task.trim()}
            className="px-5 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed
              text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
          >
            {running && !hitl && (
              <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
            )}
            {running && !hitl ? '分析中…' : '开始分析'}
          </button>
        </div>
      </div>

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

      {/* ── HITL Confirmation Card ── */}
      {hitl && (
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

      {/* Execution Timeline */}
      {steps.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-gray-500 uppercase tracking-wide">执行轨迹</p>
          <div className="flex flex-col gap-2">
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
        </div>
      )}

      {/* Harness telemetry */}
      {budget && (
        <div className="bg-gray-800/40 border border-gray-700 rounded-xl px-4 py-2.5 flex items-center gap-4 flex-wrap">
          <span className="text-[10px] text-gray-500 uppercase tracking-wide font-medium">Harness</span>
          <span className="text-xs text-gray-400">输入 {budget.input_tokens.toLocaleString()} tokens</span>
          <span className="text-xs text-gray-400">输出 {budget.output_tokens.toLocaleString()} tokens</span>
          <span className="text-xs text-gray-400">工具调用 {budget.tool_calls} 次</span>
        </div>
      )}

      {/* Newly learned skills */}
      {learnedSkills.length > 0 && (
        <div className="bg-green-900/20 border border-green-800 rounded-xl px-4 py-2.5">
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
        <div className="flex-1 min-h-0">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-3">综合报告</p>
          <div className="bg-gray-800/50 rounded-xl border border-gray-700 px-5 py-4">
            <div className="prose-custom text-sm leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{result}</ReactMarkdown>
            </div>
            <div ref={bottomRef} />
          </div>
        </div>
      )}

      {!steps.length && !result && !running && !error && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-4xl mb-3">🤖</p>
            <p className="text-sm text-gray-500">输入复杂任务，多个 Agent 顺序协作完成深度分析</p>
            <div className="flex justify-center gap-4 mt-4">
              {Object.entries(AGENT_META).map(([name, meta]) => (
                <div key={name} className="flex items-center gap-1.5 text-xs text-gray-600">
                  <span>{meta.icon}</span>
                  <span>{name}</span>
                </div>
              ))}
            </div>
            <p className="text-xs text-gray-700 mt-3">分析过程中如发现知识缺口，Agent 间可互相请求补充研究</p>
          </div>
        </div>
      )}
    </div>
  )
}
