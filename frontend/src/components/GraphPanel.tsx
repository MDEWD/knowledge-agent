import { useEffect, useRef, useState } from 'react'
import { fetchGraph, rebuildGraph } from '../api/client'
import type { GraphNode, GraphEdge, KnowledgeGraph } from '../types'

const CATEGORY_COLORS: Record<string, string> = {
  '技术': '#3b82f6',
  '商业': '#f59e0b',
  '科学': '#10b981',
  '人文': '#8b5cf6',
  '健康': '#ef4444',
  '其他': '#6b7280',
  '概念': '#06b6d4',
  '教育': '#f97316',
  '金融': '#eab308',
  '投资': '#eab308',
}

function colorFor(category: string): string {
  return CATEGORY_COLORS[category] || '#6b7280'
}

interface NodePos { x: number; y: number; vx: number; vy: number }

function runForceLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  width: number,
  height: number,
): Record<string, { x: number; y: number }> {
  if (nodes.length === 0) return {}
  const cx = width / 2, cy = height / 2

  const pos: Record<string, NodePos> = {}
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length
    const r = n.type === 'video' ? Math.min(width, height) * 0.32 : Math.min(width, height) * 0.14
    pos[n.id] = {
      x: cx + r * Math.cos(angle) + (Math.random() - 0.5) * 30,
      y: cy + r * Math.sin(angle) + (Math.random() - 0.5) * 30,
      vx: 0, vy: 0,
    }
  })

  const k = Math.sqrt((width * height) / (nodes.length + 1)) * 1.2

  for (let iter = 0; iter < 300; iter++) {
    const damping = 0.85 - (iter / 300) * 0.35
    const fx: Record<string, number> = {}
    const fy: Record<string, number> = {}
    nodes.forEach((n) => { fx[n.id] = 0; fy[n.id] = 0 })

    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j]
        const dx = pos[b.id].x - pos[a.id].x
        const dy = pos[b.id].y - pos[a.id].y
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
        // Minimum distance: video nodes need more room for their labels
        const minDist = (a.type === 'video' || b.type === 'video') ? 105 : 72
        let force = (k * k) / dist
        if (dist < minDist) force += (minDist - dist) * 1.8
        const nx = (force * dx) / dist, ny = (force * dy) / dist
        fx[a.id] -= nx; fy[a.id] -= ny
        fx[b.id] += nx; fy[b.id] += ny
      }
    }

    for (const e of edges) {
      const a = pos[e.source], b = pos[e.target]
      if (!a || !b) continue
      const dx = b.x - a.x, dy = b.y - a.y
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
      const force = (dist * dist) / k * 0.4
      const nx = (force * dx) / dist, ny = (force * dy) / dist
      fx[e.source] += nx; fy[e.source] += ny
      fx[e.target] -= nx; fy[e.target] -= ny
    }

    nodes.forEach((n) => {
      fx[n.id] += (cx - pos[n.id].x) * 0.015
      fy[n.id] += (cy - pos[n.id].y) * 0.015
    })

    const pad = 40
    nodes.forEach((n) => {
      pos[n.id].vx = (pos[n.id].vx + fx[n.id]) * damping
      pos[n.id].vy = (pos[n.id].vy + fy[n.id]) * damping
      pos[n.id].x = Math.max(pad, Math.min(width - pad, pos[n.id].x + pos[n.id].vx))
      pos[n.id].y = Math.max(pad, Math.min(height - pad, pos[n.id].y + pos[n.id].vy))
    })
  }

  return Object.fromEntries(Object.entries(pos).map(([id, p]) => [id, { x: p.x, y: p.y }]))
}

export default function GraphPanel() {
  const [graph, setGraph] = useState<KnowledgeGraph>({ nodes: [], edges: [] })
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({})
  const [hovered, setHovered] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const svgRef = useRef<SVGSVGElement>(null)
  const [dims, setDims] = useState({ w: 800, h: 500 })

  // Pan state
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [scale, setScale] = useState(1)
  const dragging = useRef(false)
  const dragStart = useRef({ mx: 0, my: 0, px: 0, py: 0 })

  useEffect(() => {
    const update = () => {
      if (svgRef.current) {
        const r = svgRef.current.getBoundingClientRect()
        setDims({ w: r.width, h: r.height })
      }
    }
    update()
    const ro = new ResizeObserver(update)
    if (svgRef.current) ro.observe(svgRef.current)
    return () => ro.disconnect()
  }, [])

  const loadGraph = async () => {
    setLoading(true)
    try {
      const g = await fetchGraph()
      setGraph(g)
      setPositions(runForceLayout(g.nodes, g.edges, dims.w, dims.h))
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadGraph() }, [])
  useEffect(() => {
    if (graph.nodes.length > 0) {
      setPositions(runForceLayout(graph.nodes, graph.edges, dims.w, dims.h))
    }
  }, [dims.w, dims.h])

  const handleRebuild = async () => {
    setRebuilding(true)
    try {
      const g = await rebuildGraph()
      setGraph(g)
      setPositions(runForceLayout(g.nodes, g.edges, dims.w, dims.h))
    } finally {
      setRebuilding(false)
    }
  }

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? 0.9 : 1.1
    setScale((s) => Math.max(0.3, Math.min(3, s * delta)))
  }

  const onMouseDown = (e: React.MouseEvent) => {
    if ((e.target as SVGElement).closest('[data-node]')) return
    dragging.current = true
    dragStart.current = { mx: e.clientX, my: e.clientY, px: pan.x, py: pan.y }
  }
  const onMouseMove = (e: React.MouseEvent) => {
    if (!dragging.current) return
    setPan({
      x: dragStart.current.px + (e.clientX - dragStart.current.mx),
      y: dragStart.current.py + (e.clientY - dragStart.current.my),
    })
  }
  const onMouseUp = () => { dragging.current = false }

  const hoveredNode = graph.nodes.find((n) => n.id === hovered)
  const connectedIds = hovered
    ? new Set(graph.edges.flatMap((e) => e.source === hovered ? [e.target] : e.target === hovered ? [e.source] : []))
    : null

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <div className="inline-block w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mb-3" />
          <p className="text-sm text-gray-400">构建知识图谱中…</p>
        </div>
      </div>
    )
  }

  if (graph.nodes.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <p className="text-4xl mb-3">🕸️</p>
          <p className="text-sm text-gray-400 mb-4">知识库为空，暂无图谱数据</p>
          <button onClick={loadGraph} className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-xl">
            刷新
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col gap-3">
      {/* Toolbar */}
      <div className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-4 text-xs text-gray-500">
          <span>{graph.nodes.filter((n) => n.type === 'video').length} 个视频</span>
          <span>{graph.nodes.filter((n) => n.type === 'concept').length} 个概念节点</span>
          <span>{graph.edges.length} 条连接</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-3 text-xs text-gray-500">
            <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-blue-500 inline-block" />视频</span>
            <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-cyan-400 inline-block" />共享概念</span>
          </div>
          <button
            onClick={handleRebuild}
            disabled={rebuilding}
            className="px-3 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg disabled:opacity-50"
          >
            {rebuilding ? '重建中…' : '重建图谱'}
          </button>
          <button
            onClick={() => { setPan({ x: 0, y: 0 }); setScale(1) }}
            className="px-3 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg"
          >
            重置视图
          </button>
        </div>
      </div>

      {/* SVG canvas */}
      <div className="flex-1 relative rounded-2xl border border-gray-700 overflow-hidden bg-gray-900/50 min-h-0">
        <svg
          ref={svgRef}
          className="w-full h-full cursor-grab active:cursor-grabbing"
          onWheel={handleWheel}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
        >
          <g transform={`translate(${pan.x},${pan.y}) scale(${scale})`}>
            {/* Edges */}
            {graph.edges.map((e, i) => {
              const a = positions[e.source], b = positions[e.target]
              if (!a || !b) return null
              const isHighlighted = hovered && (e.source === hovered || e.target === hovered)
              return (
                <line
                  key={i}
                  x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                  stroke={e.type === 'related' ? '#4b5563' : '#374151'}
                  strokeWidth={isHighlighted ? 2 : 1}
                  strokeDasharray={e.type === 'related' ? '4 3' : undefined}
                  opacity={hovered ? (isHighlighted ? 0.9 : 0.15) : 0.45}
                />
              )
            })}

            {/* Nodes */}
            {graph.nodes.map((n) => {
              const p = positions[n.id]
              if (!p) return null
              const isVideo = n.type === 'video'
              const r = isVideo ? 18 : 10
              const isHovered = hovered === n.id
              const isConnected = connectedIds?.has(n.id)
              const opacity = hovered ? (isHovered || isConnected ? 1 : 0.25) : 1
              const fill = isVideo ? colorFor(n.category) : '#06b6d4'

              return (
                <g
                  key={n.id}
                  data-node="1"
                  transform={`translate(${p.x},${p.y})`}
                  style={{ cursor: 'pointer', opacity }}
                  onMouseEnter={() => setHovered(n.id)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => n.url && window.open(n.url, '_blank')}
                >
                  <circle
                    r={isHovered ? r + 3 : r}
                    fill={fill}
                    fillOpacity={0.85}
                    stroke={isHovered ? '#fff' : 'transparent'}
                    strokeWidth={2}
                    className="transition-all duration-150"
                  />
                  <text
                    textAnchor="middle"
                    dy={r + 14}
                    fontSize={isVideo ? 10 : 9}
                    fill={isHovered ? '#fff' : '#9ca3af'}
                    stroke="#0f172a"
                    strokeWidth={3}
                    paintOrder="stroke"
                    className="pointer-events-none select-none"
                  >
                    {n.label.length > 11 ? n.label.slice(0, 10) + '…' : n.label}
                  </text>
                </g>
              )
            })}
          </g>
        </svg>

        {/* Tooltip */}
        {hoveredNode && (
          <div className="absolute bottom-4 left-4 bg-gray-800 border border-gray-600 rounded-xl px-4 py-3 max-w-xs pointer-events-none">
            <p className="text-sm font-medium text-white truncate">{hoveredNode.label}</p>
            <p className="text-xs text-gray-400 mt-0.5">
              {hoveredNode.type === 'video'
                ? `分类：${hoveredNode.category}`
                : `${hoveredNode.shared_count} 个视频共同提及`}
            </p>
            {hoveredNode.url && (
              <p className="text-xs text-blue-400 mt-0.5">点击打开视频</p>
            )}
          </div>
        )}

        {/* Zoom hint */}
        <p className="absolute bottom-4 right-4 text-xs text-gray-600">滚轮缩放 · 拖拽平移</p>
      </div>
    </div>
  )
}
