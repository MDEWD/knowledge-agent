import { useEffect, useState } from 'react'
import { fetchEvalResults, generateEvalCases, runEvals } from '../api/client'
import type { EvalResult } from '../types'

function MetricCard({ label, value, desc }: { label: string; value: number | null; desc: string }) {
  const pct = value !== null ? Math.round(value * 100) : null
  const color = pct === null ? 'text-gray-500' : pct >= 80 ? 'text-green-400' : pct >= 60 ? 'text-yellow-400' : 'text-red-400'
  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4 text-center">
      <p className={`text-2xl font-bold ${color}`}>
        {pct !== null ? `${pct}%` : '—'}
      </p>
      <p className="text-xs font-medium text-white mt-1">{label}</p>
      <p className="text-[10px] text-gray-500 mt-0.5">{desc}</p>
    </div>
  )
}

export default function EvalPanel() {
  const [result, setResult] = useState<EvalResult | null>(null)
  const [generating, setGenerating] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)

  useEffect(() => {
    fetchEvalResults().then(setResult).catch(() => {})
  }, [])

  const handleGenerate = async (force = false) => {
    setGenerating(true)
    setError('')
    try {
      const res = await generateEvalCases(force)
      setError(`已生成 ${res.count} 个测试用例，点击「运行评测」开始评分`)
    } catch (err) {
      setError(String(err))
    } finally {
      setGenerating(false)
    }
  }

  const handleRun = async () => {
    setRunning(true)
    setError('')
    try {
      const res = await runEvals()
      setResult(res)
    } catch (err) {
      setError(String(err))
    } finally {
      setRunning(false)
    }
  }

  const metrics = result?.metrics ?? {}

  return (
    <div className="mt-8 pt-6 border-t border-gray-800">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-white">RAG 评测</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            LLM-as-Judge · 自动从知识库生成测试集
            {result?.timestamp && ` · 上次评测 ${result.timestamp.slice(0, 10)}`}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => handleGenerate(true)}
            disabled={generating || running}
            className="px-3 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 disabled:opacity-40 text-gray-300 rounded-lg transition-colors"
          >
            {generating ? '生成中…' : '生成测试集'}
          </button>
          <button
            onClick={handleRun}
            disabled={running || generating}
            className="px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white rounded-lg transition-colors flex items-center gap-1.5"
          >
            {running && <span className="w-2.5 h-2.5 border border-white border-t-transparent rounded-full animate-spin" />}
            {running ? '评测中…' : '运行评测'}
          </button>
        </div>
      </div>

      {error && (
        <p className={`text-xs mb-4 px-3 py-2 rounded-lg ${error.startsWith('已生成') ? 'bg-green-900/20 text-green-400' : 'bg-red-900/20 text-red-400'}`}>
          {error}
        </p>
      )}

      {/* Metrics */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <MetricCard label="忠实度" value={metrics.faithfulness ?? null} desc="回答忠实于上下文" />
        <MetricCard label="相关性" value={metrics.answer_relevancy ?? null} desc="回答切题程度" />
        <MetricCard label="完整性" value={metrics.completeness ?? null} desc="覆盖问题所有要点" />
        <MetricCard label="连贯性" value={metrics.coherence ?? null} desc="逻辑链条清晰度" />
        <MetricCard label="Precision@3" value={metrics.precision_at_3 ?? null} desc="检索命中率" />
      </div>

      {metrics.avg_retrieval_latency_ms && (
        <p className="text-xs text-gray-600 mb-4">
          平均检索延迟：{metrics.avg_retrieval_latency_ms.toFixed(0)} ms
          {result?.case_count && ` · 共 ${result.case_count} 个测试用例`}
        </p>
      )}

      {/* Per-case results */}
      {result && result.per_case.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">逐条结果</p>
          {result.per_case.map((c, i) => (
            <div key={i} className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
              <div
                className="flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-gray-750 select-none"
                onClick={() => setExpanded(expanded === i ? null : i)}
              >
                <span className="text-xs text-gray-600 w-4 shrink-0">{i + 1}</span>
                <p className="flex-1 text-xs text-gray-300 truncate">{c.question}</p>
                <div className="flex gap-2 shrink-0">
                  {[
                    { val: c.faithfulness, label: 'F' },
                    { val: c.answer_relevancy, label: 'R' },
                    { val: c.completeness, label: 'C' },
                    { val: c.coherence, label: 'L' },
                    { val: c.precision_at_3, label: 'P' },
                  ].map(({ val, label }) => (
                    <span
                      key={label}
                      className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                        val >= 0.8 ? 'bg-green-900/40 text-green-400' :
                        val >= 0.5 ? 'bg-yellow-900/40 text-yellow-400' :
                        'bg-red-900/40 text-red-400'
                      }`}
                    >
                      {label}:{Math.round(val * 100)}
                    </span>
                  ))}
                </div>
              </div>
              {expanded === i && (
                <div className="px-4 pb-3 border-t border-gray-700 space-y-2 pt-2">
                  <p className="text-[10px] text-gray-500">来源：{c.source_title}</p>
                  {c.rubric && (
                    <div className="flex gap-3 text-[10px] text-gray-500">
                      <span>忠实度 <b className="text-gray-300">{c.rubric.faithfulness}/5</b></span>
                      <span>相关性 <b className="text-gray-300">{c.rubric.relevancy}/5</b></span>
                      <span>完整性 <b className="text-gray-300">{c.rubric.completeness}/5</b></span>
                      <span>连贯性 <b className="text-gray-300">{c.rubric.coherence}/5</b></span>
                      <span>均分 <b className="text-gray-300">{c.rubric.mean.toFixed(1)}</b></span>
                    </div>
                  )}
                  <div>
                    <p className="text-[10px] text-gray-600 mb-0.5">RAG 生成答案：</p>
                    <p className="text-xs text-gray-400 leading-relaxed">{c.answer}</p>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {!result?.per_case?.length && !running && !generating && (
        <div className="text-center py-8">
          <p className="text-3xl mb-2">📊</p>
          <p className="text-sm text-gray-500">先生成测试集，再运行评测</p>
        </div>
      )}
    </div>
  )
}
