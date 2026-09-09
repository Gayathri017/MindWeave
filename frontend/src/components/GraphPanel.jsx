import { useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { getGraph } from '../lib/api'

const ORANGE = '#D97A34'
const SAGE = '#8A9464'
const SMALL = '#8C8564'
const THREAD = 'rgba(240, 234, 214, 0.16)'

export default function GraphPanel({ refreshKey, width }) {
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const containerRef = useRef(null)
  const [size, setSize] = useState({ width: 380, height: 600 })

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      try {
        const data = await getGraph()
        if (!cancelled) {
          setGraph(data)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [refreshKey])

  useEffect(() => {
    function updateSize() {
      if (containerRef.current) {
        setSize({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        })
      }
    }
    updateSize()
    window.addEventListener('resize', updateSize)
    return () => window.removeEventListener('resize', updateSize)
  }, [])

  // Node size and color reflect how connected a concept is -- a concept
  // that keeps reappearing across your notes should visibly stand out,
  // not just exist as an identical dot among fifty others.
  const graphData = useMemo(() => {
    const degree = {}
    for (const edge of graph.edges) {
      degree[edge.source] = (degree[edge.source] || 0) + 1
      degree[edge.target] = (degree[edge.target] || 0) + 1
    }
    return {
      nodes: graph.nodes.map((node) => ({ ...node, degree: degree[node.id] || 0 })),
      links: graph.edges.map((edge) => ({
        source: edge.source,
        target: edge.target,
        weight: edge.weight,
      })),
    }
  }, [graph])

  return (
    <div className="right-panel" style={{ width }}>
      <div className="header wordmark">Your graph</div>
      <div className="subheader">
        {graph.nodes.length} concept{graph.nodes.length === 1 ? '' : 's'} &middot;{' '}
        {graph.edges.length} connection{graph.edges.length === 1 ? '' : 's'}
      </div>
      {graph.nodes.length > 0 && (
        <p className="graph-hint">Drag a concept to arrange it your way &middot; double-click to release it</p>
      )}
      <div className="graph-canvas" ref={containerRef}>
        {loading && <p className="panel-hint">Loading&hellip;</p>}
        {error && <p className="panel-hint error">{error}</p>}
        {!loading && !error && graph.nodes.length === 0 && (
          <p className="panel-hint">Save something to start your graph.</p>
        )}
        {!loading && !error && graph.nodes.length > 0 && (
          <ForceGraph2D
            graphData={graphData}
            width={size.width}
            height={size.height}
            backgroundColor="transparent"
            linkColor={() => THREAD}
            linkWidth={(link) => Math.min(1 + link.weight * 0.5, 4)}
            nodeRelSize={4}
            nodeLabel={(node) => node.name}
            nodeCanvasObject={(node, ctx, globalScale) => {
              const radius = 4 + Math.min(node.degree, 6) * 1.3
              const color = node.degree >= 3 ? ORANGE : node.degree >= 1 ? SAGE : SMALL
              const isPinned = node.fx !== undefined

              ctx.shadowColor = color
              ctx.shadowBlur = 10
              ctx.fillStyle = color
              ctx.beginPath()
              ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI)
              ctx.fill()
              ctx.shadowBlur = 0

              // A pinned node (you dragged it) gets a faint ring, so it
              // reads as "placed on purpose" rather than just resting there.
              if (isPinned) {
                ctx.strokeStyle = 'rgba(240, 234, 214, 0.55)'
                ctx.lineWidth = 1.5
                ctx.beginPath()
                ctx.arc(node.x, node.y, radius + 3, 0, 2 * Math.PI)
                ctx.stroke()
              }

              const fontSize = 11.5 / globalScale
              ctx.font = `${fontSize}px Inter, sans-serif`
              ctx.fillStyle = node.degree >= 2 ? '#F0EAD6' : '#B8B296'
              ctx.textAlign = 'left'
              ctx.textBaseline = 'middle'
              ctx.fillText(node.name, node.x + radius + 4, node.y)
            }}
            onNodeDragEnd={(node) => {
              // Fix the node at wherever it was dropped -- the simulation
              // will no longer pull it back, so your arrangement sticks.
              node.fx = node.x
              node.fy = node.y
            }}
            onNodeClick={(node, event) => {
              // Double-click releases a pinned node back to auto-layout.
              if (event.detail === 2) {
                node.fx = undefined
                node.fy = undefined
              }
            }}
            cooldownTicks={100}
          />
        )}
      </div>
    </div>
  )
}