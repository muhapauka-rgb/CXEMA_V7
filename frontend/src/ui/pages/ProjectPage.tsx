import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { apiGet } from '../api'

type Project = {
  id: number
  title: string
  project_price_total: number
  expected_from_client_total: number
}
type Computed = {
  project_id: number
  expenses_total: number
  agency_fee: number
  extra_profit_total: number
  in_pocket: number
  diff: number
}

export default function ProjectPage() {
  const { id } = useParams()
  const [project, setProject] = useState<Project | null>(null)
  const [computed, setComputed] = useState<Computed | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    setError(null)
    apiGet<Project>(`/api/projects/${id}`).then(setProject).catch((e) => setError(String(e)))
    apiGet<Computed>(`/api/projects/${id}/computed`).then(setComputed).catch((e) => setError(String(e)))
  }, [id])

  if (error) return <div className="card">{error}</div>
  if (!project) return <div className="card">Загрузка…</div>

  return (
    <div className="grid">
      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <div>
            <div className="h1">{project.title}</div>
            <div className="muted">Стоимость: {project.project_price_total} • Ждём всего: {project.expected_from_client_total}</div>
          </div>
          <Link className="btn" to="/projects">← назад</Link>
        </div>
      </div>

      <div className="card">
        <div className="h1">Финансы (MVP computed)</div>
        {computed ? (
          <div className="grid grid-2">
            <div className="card">Расходы: {computed.expenses_total}</div>
            <div className="card">Агентские (10%): {computed.agency_fee}</div>
            <div className="card">Доп прибыль (мешочки): {computed.extra_profit_total}</div>
            <div className="card">В кармане: {computed.in_pocket}</div>
            <div className="card">diff: {computed.diff}</div>
          </div>
        ) : (
          <div className="muted">нет данных</div>
        )}
        <div className="muted" style={{ marginTop: 10 }}>
          Следующий шаг: карточки групп/позиций и импорт “сторонней сметы”.
        </div>
      </div>
    </div>
  )
}
