import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiGet, apiPost } from '../api'

type Project = {
  id: number
  title: string
  project_price_total: number
  expected_from_client_total: number
}

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [title, setTitle] = useState('Новый проект')
  const [error, setError] = useState<string | null>(null)

  const load = () => apiGet<Project[]>('/api/projects').then(setProjects).catch((e) => setError(String(e)))

  useEffect(() => { load() }, [])

  async function create() {
    setError(null)
    await apiPost<Project>('/api/projects', { title, project_price_total: 0, expected_from_client_total: 0 })
    await load()
  }

  return (
    <div className="grid">
      <div className="card">
        <div className="h1">Проекты</div>
        <div className="row">
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
          <button className="btn" onClick={create}>+ проект</button>
        </div>
        {error && <div className="muted" style={{ marginTop: 8 }}>{error}</div>}
      </div>

      <div className="grid grid-2">
        {projects.map(p => (
          <Link key={p.id} to={`/projects/${p.id}`} className="card">
            <div style={{ fontWeight: 700 }}>{p.title}</div>
            <div className="muted" style={{ marginTop: 8 }}>Стоимость: {p.project_price_total}</div>
            <div className="muted">Ждём всего: {p.expected_from_client_total}</div>
          </Link>
        ))}
      </div>
    </div>
  )
}
