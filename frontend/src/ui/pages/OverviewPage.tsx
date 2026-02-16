import { useEffect, useMemo, useState } from 'react'
import ReactFlow, { Background, Controls, Node, Edge } from 'reactflow'
import 'reactflow/dist/style.css'
import { apiGet } from '../api'

type OverviewMap = { at: string, root: { title: string, children?: any[] } }

function todayISO() {
  const d = new Date()
  const z = (n: number) => String(n).padStart(2,'0')
  return `${d.getFullYear()}-${z(d.getMonth()+1)}-${z(d.getDate())}`
}

function toFlow(map: OverviewMap): { nodes: Node[], edges: Edge[] } {
  const nodes: Node[] = []
  const edges: Edge[] = []

  let x = 0
  let y = 0
  const gapX = 260
  const gapY = 90
  let idCounter = 1

  const makeId = () => `n${idCounter++}`

  const walk = (title: string, children: any[] | undefined, parentId: string | null, depth: number, index: number) => {
    const id = makeId()
    const pos = { x: depth * gapX, y: (index + y) * gapY }
    nodes.push({ id, data: { label: title }, position: pos, style: { background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 12, padding: 10, color: '#e8ecf3', width: 240 } })
    if (parentId) edges.push({ id: `e-${parentId}-${id}`, source: parentId, target: id })
    if (children && children.length) {
      children.forEach((c, i) => walk(c.title, c.children, id, depth + 1, i))
    }
    return id
  }

  walk(map.root.title, map.root.children, null, 0, 0)
  return { nodes, edges }
}

export default function OverviewPage() {
  const [at, setAt] = useState<string>(todayISO())
  const [map, setMap] = useState<OverviewMap | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setError(null)
    apiGet<OverviewMap>(`/api/overview/map?at=${at}`)
      .then(setMap)
      .catch((e) => setError(String(e)))
  }, [at])

  const flow = useMemo(() => (map ? toFlow(map) : { nodes: [], edges: [] }), [map])

  return (
    <div className="grid">
      <div className="card">
        <div className="row">
          <div className="h1">Итоги — дата T</div>
          <input className="input" style={{ maxWidth: 200 }} type="date" value={at} onChange={(e) => setAt(e.target.value)} />
          <div className="muted">Backend: :8011 • Frontend: :3011</div>
        </div>
        {error && <div className="muted" style={{ marginTop: 8 }}>{error}</div>}
      </div>

      <div className="card" style={{ height: 560 }}>
        <ReactFlow nodes={flow.nodes} edges={flow.edges} fitView>
          <Background />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  )
}
