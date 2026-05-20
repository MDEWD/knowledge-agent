import { useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { streamAgentRun } from '../api/client'
import type { AgentStep } from '../types'

const AGENT_META: Record<string, { icon: string; color: string; desc: string }> = {
  ResearchAgent:  { icon: '🔍', color: 'blue',   desc: '知识库检索' },
  AnalysisAgent:  { icon: '📊', color: 'purple', desc: '深度分析' },
  WritingAgent:   { icon: '✍️', color: 'green',  desc: '报告撰写' },
}

const COLOR_CLASSES: Record<string, string> = {
  blue:   'bg-blue-900/30 border-blue-700 text-blue-300',
  purple: 'bg-purple-900/30 border-purple-700 text-purple-300',
  green:  'bg-green-900/30 border-green-700 text-green-300',
}

export default function AgentPanel() {
  const [task, setTask] = useState('')
  const [running, setRunning] = useState(false)
  const [steps, setSteps] = useState<AgentStep[]>([])
  const [result, setResult] = useState('')
  const [error, setError] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  const run = async () => {
    const t = task.trim()
    if (!t || running) return
    setRunning(true)
    setSteps([])
    setResult('')
    setError('')

    try {
      for await (const event of streamAgentRun(t)) {
        if (event.type === 'plan') {
          setSteps(event.steps)
        } else if (event.type === 'agent_start') {
          setSteps((prev) =>
            prev.map((s) =>
              s.agent === event.agent ? { ...s, status: 'running' } : s,
            ),
          )
        } else if (event.type === 'agent_done') {
          setSteps((prev) =>
            prev.map((s) =>
              s.agent === event.agent
                ? { ...s, status: 'done', summary: event.summary }
                : s,
            ),
          )
        } else if (event.type === 'text') {
          setResult((r) => r + event.content)
          bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
        } else if (event.type === 'error') {
          setError(event.message)
        }
      }
    } catch (err) {
      setError(String(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="h-full flex flex-col gap-5 overflow-y-auto pb-4">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-white mb-1">深度分析</h2>
        <p className="text-sm text-gray-400">
          多 Agent 并行协作：ResearchAgent + AnalysisAgent 同步执行，WritingAgent 综合输出
        </p>
      </div>

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
            {running && (
              <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
            )}
            {running ? '分析中…' : '开始分析'}
          </button>
        </div>
      </div>

      {/* Execution Timeline */}
      {steps.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-gray-500 uppercase tracking-wide">执行轨迹</p>
          <div className="flex flex-col gap-2">
            {steps.map((step, i) => {
              const meta = AGENT_META[step.agent] ?? { icon: '🤖', color: 'blue', desc: step.agent }
              const colorCls = COLOR_CLASSES[meta.color] ?? COLOR_CLASSES.blue
              return (
                <div key={i} className={`rounded-xl border px-4 py-3 ${colorCls} transition-all`}>
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
                  {step.status === 'done' && step.summary && (
                    <p className="text-xs opacity-60 mt-1.5 line-clamp-2 border-t border-current/20 pt-1.5">
                      {step.summary}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
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

      {!steps.length && !result && !running && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-4xl mb-3">🤖</p>
            <p className="text-sm text-gray-500">输入复杂任务，多个 Agent 并行协作完成深度分析</p>
            <div className="flex justify-center gap-4 mt-4">
              {Object.entries(AGENT_META).map(([name, meta]) => (
                <div key={name} className="flex items-center gap-1.5 text-xs text-gray-600">
                  <span>{meta.icon}</span>
                  <span>{name}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
