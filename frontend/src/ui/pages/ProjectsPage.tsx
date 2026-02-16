import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { apiGet, apiPatch, apiPost } from "../api"

type Project = {
  id: number
  title: string
  client_name?: string | null
  client_email?: string | null
  client_phone?: string | null
  project_price_total: number
  expected_from_client_total: number
}

type CreateProjectForm = {
  title: string
  client_name: string
  client_email: string
  client_phone: string
}

const EMPTY_FORM: CreateProjectForm = {
  title: "",
  client_name: "",
  client_email: "",
  client_phone: "",
}

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [form, setForm] = useState<CreateProjectForm>(EMPTY_FORM)
  const [editingProjectId, setEditingProjectId] = useState<number | null>(null)
  const [editingTitle, setEditingTitle] = useState("")
  const [savingTitle, setSavingTitle] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    try {
      setError(null)
      const data = await apiGet<Project[]>("/api/projects")
      setProjects(data)
    } catch (e) {
      setError(String(e))
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function create() {
    const title = form.title.trim()
    if (!title) {
      setError("Укажи название проекта")
      return
    }
    try {
      setError(null)
      setCreating(true)
      await apiPost<Project>("/api/projects", {
        title,
        client_name: form.client_name.trim() || null,
        client_email: form.client_email.trim() || null,
        client_phone: form.client_phone.trim() || null,
        project_price_total: 0,
        expected_from_client_total: 0,
      })
      setForm(EMPTY_FORM)
      await load()
    } catch (e) {
      setError(String(e))
    } finally {
      setCreating(false)
    }
  }

  function startEditTitle(project: Project) {
    setEditingProjectId(project.id)
    setEditingTitle(project.title)
  }

  function cancelEditTitle() {
    setEditingProjectId(null)
    setEditingTitle("")
  }

  async function saveTitle(project: Project) {
    const nextTitle = editingTitle.trim()
    if (!nextTitle) {
      setError("Название проекта не может быть пустым")
      return
    }
    if (nextTitle === project.title) {
      cancelEditTitle()
      return
    }
    try {
      setError(null)
      setSavingTitle(true)
      const updated = await apiPatch<Project>(`/api/projects/${project.id}`, { title: nextTitle })
      setProjects((prev) => prev.map((p) => (p.id === project.id ? updated : p)))
      cancelEditTitle()
    } catch (e) {
      setError(String(e))
    } finally {
      setSavingTitle(false)
    }
  }

  return (
    <div className="grid">
      <div className="panel top-panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <div className="h1">Проекты</div>
          </div>
          <div className="muted">Всего проектов: {projects.length}</div>
        </div>
      </div>

      <div className="panel">
        <div className="h1" style={{ marginBottom: 8 }}>Добавить проект</div>
        <div className="grid grid-2">
          <input
            className="input"
            placeholder="Название проекта"
            value={form.title}
            onChange={(e) => setForm((prev) => ({ ...prev, title: e.target.value }))}
          />
          <input
            className="input"
            placeholder="Организация"
            value={form.client_name}
            onChange={(e) => setForm((prev) => ({ ...prev, client_name: e.target.value }))}
          />
          <input
            className="input"
            placeholder="Email клиента"
            value={form.client_email}
            onChange={(e) => setForm((prev) => ({ ...prev, client_email: e.target.value }))}
          />
          <input
            className="input"
            placeholder="Телефон клиента"
            value={form.client_phone}
            onChange={(e) => setForm((prev) => ({ ...prev, client_phone: e.target.value }))}
          />
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn" disabled={creating} onClick={() => void create()}>Добавить проект</button>
        </div>
      </div>

      <div className="grid grid-2">
        {projects.map((p) => {
          const isEditing = editingProjectId === p.id
          return (
            <div key={p.id} className="card">
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                {!isEditing && (
                  <button
                    className="title-btn"
                    onClick={() => startEditTitle(p)}
                  >
                    {p.title}
                  </button>
                )}
                {isEditing && (
                  <div className="row" style={{ flex: 1 }}>
                    <input
                      className="input"
                      value={editingTitle}
                      autoFocus
                      onChange={(e) => setEditingTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault()
                          void saveTitle(p)
                        }
                        if (e.key === "Escape") {
                          e.preventDefault()
                          cancelEditTitle()
                        }
                      }}
                    />
                    <button className="btn" disabled={savingTitle} onClick={() => void saveTitle(p)}>Сохранить</button>
                    <button className="btn" disabled={savingTitle} onClick={cancelEditTitle}>Отмена</button>
                  </div>
                )}
                {!isEditing && <Link to={`/projects/${p.id}`} className="btn">Открыть</Link>}
              </div>
              <div className="muted" style={{ marginTop: 8 }}>Организация: {p.client_name || "—"}</div>
              <div className="muted">Email: {p.client_email || "—"}</div>
              <div className="muted">Телефон: {p.client_phone || "—"}</div>
            </div>
          )
        })}
      </div>

      {error && (
        <div className="panel">
          <div className="muted" style={{ color: "#ff9a9a" }}>{error}</div>
        </div>
      )}
    </div>
  )
}
