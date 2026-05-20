import { useEffect, useState } from 'react'
import { fetchStats } from '../api/client'
import type { Stats } from '../types'
import EvalPanel from './EvalPanel'

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function Bar({ value, max, color = 'bg-blue-500' }: { value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-700 rounded-full h-1.5">
        <div className={`${color} h-1.5 rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400 w-5 text-right">{value}</span>
    </div>
  )
}

const CATEGORY_COLORS: Record<string, string> = {
  'AI与科技': 'bg-blue-500',
  '财经理财': 'bg-green-500',
  '心理学': 'bg-purple-500',
  '商业创业': 'bg-yellow-500',
  '健康生活': 'bg-teal-500',
  '教育学习': 'bg-orange-500',
  '历史文化': 'bg-red-400',
  '娱乐综艺': 'bg-pink-500',
  '科学探索': 'bg-cyan-500',
  '其他': 'bg-gray-500',
}

export default function StatsPanel() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchStats()
      .then(setStats)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="h-full flex items-center justify-center text-gray-500 text-sm">加载中…</div>
  if (!stats) return null

  const topCategory = Object.entries(stats.categories).sort((a, b) => b[1] - a[1])[0]
  const thisWeek = stats.weekly[stats.weekly.length - 1]?.count ?? 0
  const maxWeekly = Math.max(...stats.weekly.map((w) => w.count), 1)
  const maxCat = Math.max(...Object.values(stats.categories), 1)
  const maxTag = stats.top_tags[0]?.count ?? 1

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl space-y-6">
        <div>
          <h2 className="text-lg font-semibold text-white mb-1">知识库统计</h2>
          <p className="text-xs text-gray-500">你的学习数据总览</p>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: '视频总数', value: `${stats.total}`, sub: '个' },
            { label: '内容时长', value: formatDuration(stats.total_duration), sub: '总计' },
            { label: '最多分类', value: topCategory?.[0] ?? '—', sub: `${topCategory?.[1] ?? 0} 个` },
            { label: '本周新增', value: `${thisWeek}`, sub: '个视频' },
          ].map((card) => (
            <div key={card.label} className="bg-gray-800 rounded-xl p-4 border border-gray-700">
              <p className="text-xs text-gray-500 mb-1">{card.label}</p>
              <p className="text-xl font-bold text-white truncate">{card.value}</p>
              <p className="text-xs text-gray-600 mt-0.5">{card.sub}</p>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          {/* Category breakdown */}
          <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
            <h3 className="text-sm font-medium text-gray-300 mb-3">分类分布</h3>
            <div className="space-y-2.5">
              {Object.entries(stats.categories)
                .sort((a, b) => b[1] - a[1])
                .map(([cat, count]) => (
                  <div key={cat}>
                    <div className="flex justify-between mb-1">
                      <span className="text-xs text-gray-400">{cat}</span>
                    </div>
                    <Bar value={count} max={maxCat} color={CATEGORY_COLORS[cat] ?? 'bg-gray-500'} />
                  </div>
                ))}
            </div>
          </div>

          {/* Top tags */}
          <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
            <h3 className="text-sm font-medium text-gray-300 mb-3">高频标签 Top 15</h3>
            <div className="space-y-2">
              {stats.top_tags.map(({ tag, count }) => (
                <div key={tag}>
                  <div className="flex justify-between mb-1">
                    <span className="text-xs text-gray-400">#{tag}</span>
                  </div>
                  <Bar value={count} max={maxTag} color="bg-purple-500" />
                </div>
              ))}
              {stats.top_tags.length === 0 && (
                <p className="text-xs text-gray-600">暂无标签数据</p>
              )}
            </div>
          </div>
        </div>

        {/* Weekly trend */}
        <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
          <h3 className="text-sm font-medium text-gray-300 mb-4">近 8 周新增趋势</h3>
          <div className="flex items-end gap-2 h-24">
            {stats.weekly.map((w, i) => {
              const pct = maxWeekly > 0 ? (w.count / maxWeekly) * 100 : 0
              const isLast = i === stats.weekly.length - 1
              return (
                <div key={w.label} className="flex-1 flex flex-col items-center gap-1">
                  <span className="text-[10px] text-gray-500">{w.count > 0 ? w.count : ''}</span>
                  <div className="w-full flex items-end" style={{ height: '64px' }}>
                    <div
                      className={`w-full rounded-t transition-all duration-500 ${isLast ? 'bg-blue-500' : 'bg-gray-600'}`}
                      style={{ height: `${Math.max(pct, w.count > 0 ? 8 : 0)}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-gray-600 rotate-0">{w.label}</span>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      <EvalPanel />
    </div>
  )
}
