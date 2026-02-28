import { useEffect, useMemo, useRef, useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { apiDelete, apiGet, apiPatch, apiPost } from "../api"
import { openNativePicker } from "../datePicker"

type SnapshotProject = {
  project_id: number
  title: string
  active: boolean
  received_to_date: number
  spent_to_date: number
  balance_to_date: number
  expected_total: number
  remaining: number
  agency_fee_to_date: number
  extra_profit_to_date: number
  in_pocket_to_date: number
}

type OverviewSnapshot = {
  meta: { at: string; currency: string }
  totals: {
    active_projects_count: number
    received_total: number
    spent_total: number
    balance_total: number
    planned_total: number
    expected_total: number
    agency_fee_to_date: number
    extra_profit_to_date: number
    in_pocket_to_date: number
  }
  projects: SnapshotProject[]
}

type OverviewMonthRange = {
  min_month: string
  max_month: string
}

type ProjectMeta = {
  id: number
  title: string
  client_name?: string | null
  client_email?: string | null
  client_phone?: string | null
  card_image_data?: string | null
  sort_order: number
  is_paused: boolean
  created_at: string
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

const MAX_CARD_IMAGE_BYTES = 5 * 1024 * 1024

function toMoney(v: number): string {
  return Number(v || 0).toLocaleString("ru-RU", { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function monthKey(d: Date): string {
  const z = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}`
}

function parseMonthKey(key: string): Date {
  const [y, m] = key.split("-").map((v) => Number(v))
  if (!Number.isFinite(y) || !Number.isFinite(m) || m < 1 || m > 12) {
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), 1)
  }
  return new Date(y, m - 1, 1)
}

function monthLabelRu(key: string): string {
  const d = parseMonthKey(key)
  const month = new Intl.DateTimeFormat("ru-RU", { month: "long" }).format(d)
  return `${month} ${d.getFullYear()}`
}

function buildMonthRange(start: Date, end: Date): string[] {
  const out: string[] = []
  let y = start.getFullYear()
  let m = start.getMonth()
  const ey = end.getFullYear()
  const em = end.getMonth()
  while (y < ey || (y === ey && m <= em)) {
    out.push(monthKey(new Date(y, m, 1)))
    m += 1
    if (m > 11) {
      m = 0
      y += 1
    }
  }
  return out
}

function snapshotAtFromMonth(selected: string): string {
  const m = parseMonthKey(selected)
  const at = new Date(m.getFullYear(), m.getMonth() + 1, 0)
  const z = (n: number) => String(n).padStart(2, "0")
  return `${at.getFullYear()}-${z(at.getMonth() + 1)}-${z(at.getDate())}`
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error("Не удалось прочитать файл"))
    reader.onload = () => resolve(String(reader.result || ""))
    reader.readAsDataURL(file)
  })
}

export default function OverviewPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useSearchParams()
  const [snapshot, setSnapshot] = useState<OverviewSnapshot | null>(null)
  const [leftProjects, setLeftProjects] = useState<ProjectMeta[]>([])
  const [draggingProjectId, setDraggingProjectId] = useState<number | null>(null)
  const [projectToDelete, setProjectToDelete] = useState<ProjectMeta | null>(null)
  const [deletingProjectId, setDeletingProjectId] = useState<number | null>(null)
  const [projectsMeta, setProjectsMeta] = useState<ProjectMeta[]>([])
  const [months, setMonths] = useState<string[]>([monthKey(new Date())])
  const [selectedMonth, setSelectedMonth] = useState(monthKey(new Date()))
  const [form, setForm] = useState<CreateProjectForm>(EMPTY_FORM)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [projectSearch, setProjectSearch] = useState("")
  const monthPickerRef = useRef<HTMLInputElement | null>(null)

  const createOpen = search.get("create") === "1"
  const at = useMemo(() => snapshotAtFromMonth(selectedMonth), [selectedMonth])
  const selectedIdx = Math.max(0, months.indexOf(selectedMonth))
  const snapshotById = useMemo(
    () => new Map((snapshot?.projects || []).map((p) => [p.project_id, p])),
    [snapshot],
  )
  const filteredLeftProjects = useMemo(() => {
    const q = projectSearch.trim().toLowerCase()
    if (!q) return leftProjects
    return leftProjects.filter((p) => p.title.toLowerCase().includes(q))
  }, [leftProjects, projectSearch])
  const filteredSnapshotProjects = useMemo(() => {
    const q = projectSearch.trim().toLowerCase()
    const base = snapshot?.projects || []
    if (!q) return base
    const ids = new Set(filteredLeftProjects.map((p) => p.id))
    return base.filter((p) => ids.has(p.project_id) || p.title.toLowerCase().includes(q))
  }, [snapshot, filteredLeftProjects, projectSearch])

  async function loadProjectsMeta() {
    const data = await apiGet<ProjectMeta[]>("/api/projects")
    setProjectsMeta(data)
    setLeftProjects(data)
  }

  async function loadMonthRange() {
    const rangeRaw = await apiGet<OverviewMonthRange>("/api/overview/month-range")
    const start = parseMonthKey(rangeRaw.min_month)
    const end = parseMonthKey(rangeRaw.max_month)
    const range = buildMonthRange(start <= end ? start : end, start <= end ? end : start)
    setMonths(range)
    if (!range.includes(selectedMonth)) {
      setSelectedMonth(range[range.length - 1])
    }
  }

  async function loadSnapshot() {
    const snap = await apiGet<OverviewSnapshot>(`/api/overview/snapshot?at=${at}`)
    setSnapshot(snap)
  }

  async function loadAll() {
    try {
      setError(null)
      await Promise.all([loadProjectsMeta(), loadMonthRange(), loadSnapshot()])
    } catch (e) {
      setError(String(e))
    }
  }

  async function createProject() {
    const title = form.title.trim()
    if (!title) {
      setError("Укажи название проекта")
      return
    }
    try {
      setError(null)
      setCreating(true)
      const created = await apiPost<ProjectMeta>("/api/projects", {
        title,
        client_name: form.client_name.trim() || null,
        client_email: form.client_email.trim() || null,
        client_phone: form.client_phone.trim() || null,
        project_price_total: 0,
        expected_from_client_total: 0,
      })
      setForm(EMPTY_FORM)
      setSearch((prev) => {
        const next = new URLSearchParams(prev)
        next.delete("create")
        return next
      })
      navigate(`/projects/${created.id}`)
    } catch (e) {
      setError(String(e))
    } finally {
      setCreating(false)
    }
  }

  useEffect(() => {
    void loadAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    setError(null)
    void loadSnapshot().catch((e) => setError(String(e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [at])

  function reorderProjects(source: ProjectMeta[], fromProjectId: number, toProjectId: number): ProjectMeta[] {
    if (fromProjectId === toProjectId) return source
    const fromIdx = source.findIndex((p) => p.id === fromProjectId)
    const toIdx = source.findIndex((p) => p.id === toProjectId)
    if (fromIdx < 0 || toIdx < 0) return source
    const copy = [...source]
    const [moved] = copy.splice(fromIdx, 1)
    copy.splice(toIdx, 0, moved)
    return copy
  }

  async function persistProjectOrder(nextOrder: ProjectMeta[]) {
    try {
      await apiPost("/api/projects/reorder", {
        project_ids: nextOrder.map((p) => p.id),
      })
      setProjectsMeta(nextOrder)
    } catch (e) {
      setError(String(e))
      setLeftProjects(projectsMeta)
    }
  }

  async function deleteProjectConfirmed() {
    if (!projectToDelete) return
    try {
      setError(null)
      setDeletingProjectId(projectToDelete.id)
      await apiDelete(`/api/projects/${projectToDelete.id}`)
      setProjectToDelete(null)
      await loadAll()
    } catch (e) {
      setError(String(e))
    } finally {
      setDeletingProjectId(null)
    }
  }

  async function toggleProjectPause(project: ProjectMeta) {
    try {
      setError(null)
      await apiPatch<ProjectMeta>(`/api/projects/${project.id}`, { is_paused: !project.is_paused })
      await loadAll()
    } catch (e) {
      setError(String(e))
    }
  }

  function upsertProjectMeta(updated: ProjectMeta) {
    setLeftProjects((prev) => prev.map((p) => (p.id === updated.id ? { ...p, ...updated } : p)))
    setProjectsMeta((prev) => prev.map((p) => (p.id === updated.id ? { ...p, ...updated } : p)))
  }

  async function uploadProjectImage(project: ProjectMeta, file: File) {
    if (!file.type.startsWith("image/")) {
      setError("Можно загрузить только изображение")
      return
    }
    if (file.size > MAX_CARD_IMAGE_BYTES) {
      setError("Картинка слишком большая (максимум 5 МБ)")
      return
    }
    try {
      setError(null)
      const dataUrl = await fileToDataUrl(file)
      const updated = await apiPatch<ProjectMeta>(`/api/projects/${project.id}`, {
        card_image_data: dataUrl,
      })
      upsertProjectMeta(updated)
    } catch (e) {
      setError(String(e))
    }
  }

  useEffect(() => {
    if (!createOpen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !creating) {
        setSearch((prev) => {
          const next = new URLSearchParams(prev)
          next.delete("create")
          return next
        })
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [createOpen, creating, setSearch])

  return (
    <>
    <div className={`grid ${createOpen ? "page-content-muted" : ""}`}>
      <div className="sticky-stack">
        <div className="overview-search-row">
          <div className="overview-search-wrap">
            <input
              className="overview-search-input"
              placeholder="Поиск проекта"
              value={projectSearch}
              onChange={(e) => setProjectSearch(e.target.value)}
            />
            <span className="overview-search-icon" aria-hidden="true">
              🔍
            </span>
          </div>
        </div>
        <div className="panel top-panel">
          <div className="timeline-panel">
            <div className="timeline-head">
              <button
                className="timeline-current-month"
                onClick={() => openNativePicker(monthPickerRef.current, true)}
              >
                {monthLabelRu(selectedMonth)}
              </button>
            </div>
            <div className="timeline-current-row">
              <input
                ref={monthPickerRef}
                className="timeline-month-picker-hidden"
                type="month"
                value={selectedMonth}
                min={months[0] || undefined}
                max={months[months.length - 1] || undefined}
                onChange={(e) => {
                  if (months.includes(e.target.value)) setSelectedMonth(e.target.value)
                }}
              />
            </div>
            <input
              className="timeline-range"
              type="range"
              min={0}
              max={Math.max(0, months.length - 1)}
              step={1}
              value={selectedIdx}
              onChange={(e) => {
                const idx = Number(e.target.value)
                setSelectedMonth(months[idx] || months[months.length - 1])
              }}
            />
          </div>
        </div>

        {snapshot && (
          <div className="overview-kpi-strip">
            <div className="kpi-card">
              <div className="muted">Проекты</div>
              <div className="kpi-value">{snapshot.totals.active_projects_count}</div>
            </div>
            <div className="kpi-card">
              <div className="muted">Получено</div>
              <div className="kpi-value">{toMoney(snapshot.totals.received_total)}</div>
            </div>
            <div className="kpi-card">
              <div className="muted">Потрачено</div>
              <div className="kpi-value">{toMoney(snapshot.totals.spent_total)}</div>
            </div>
            <div className="kpi-card">
              <div className="muted">Агентские</div>
              <div className="kpi-value">{toMoney(snapshot.totals.agency_fee_to_date)}</div>
            </div>
            <div className="kpi-card">
              <div className="muted">Доп прибыль</div>
              <div className="kpi-value">{toMoney(snapshot.totals.extra_profit_to_date)}</div>
            </div>
            <div className="kpi-card">
              <div className="muted">Всего в кармане</div>
              <div className="kpi-value accent">{toMoney(snapshot.totals.in_pocket_to_date)}</div>
            </div>
            <div className="kpi-card">
              <div className="muted">Баланс</div>
              <div className={`kpi-value ${snapshot.totals.balance_total >= 0 ? "ok" : "bad"}`}>
                {toMoney(snapshot.totals.balance_total)}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="classic-layout">
        <div className="panel">
          <div className="grid">
            {filteredLeftProjects.map((p) => {
              const metrics = snapshotById.get(p.id)
              return (
                <Link
                  key={p.id}
                  to={`/projects/${p.id}`}
                  className={`project-tile classic-project-tile ${p.is_paused ? "paused-project-tile" : ""}`}
                  draggable={!p.is_paused}
                  onDragStart={(e) => {
                    e.dataTransfer.effectAllowed = "move"
                    e.dataTransfer.setData("text/plain", String(p.id))
                    setDraggingProjectId(p.id)
                  }}
                  onDragEnd={() => setDraggingProjectId(null)}
                  onDragOver={(e) => {
                    e.preventDefault()
                    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                      e.dataTransfer.dropEffect = "copy"
                      return
                    }
                    if (draggingProjectId === null) return
                    setLeftProjects((prev) => reorderProjects(prev, draggingProjectId, p.id))
                  }}
                  onDrop={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    const droppedFile = e.dataTransfer.files?.[0]
                    if (droppedFile) {
                      void uploadProjectImage(p, droppedFile)
                      return
                    }
                    if (draggingProjectId === null) return
                    const nextOrder = reorderProjects(leftProjects, draggingProjectId, p.id)
                    setDraggingProjectId(null)
                    setLeftProjects(nextOrder)
                    void persistProjectOrder(nextOrder)
                  }}
                >
                  <button
                    type="button"
                    className="project-delete-btn"
                    aria-label={`Удалить проект ${p.title}`}
                    title="Удалить проект"
                    onMouseDown={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                    }}
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      setProjectToDelete(p)
                    }}
                  >
                    ×
                  </button>
                  <button
                    type="button"
                    className="project-pause-btn"
                    aria-label={p.is_paused ? `Возобновить проект ${p.title}` : `Поставить на паузу проект ${p.title}`}
                    title={p.is_paused ? "Возобновить" : "Пауза"}
                    onMouseDown={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                    }}
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      void toggleProjectPause(p)
                    }}
                  >
                    {p.is_paused ? "▶" : "‖"}
                  </button>
                  <div className="project-tile-content">
                    <div className="project-tile-thumb-wrap">
                      {p.card_image_data ? (
                        <img
                          className="project-tile-thumb"
                          src={p.card_image_data}
                          alt={`Миниатюра ${p.title}`}
                        />
                      ) : (
                        <div className="project-tile-thumb project-tile-thumb-empty" />
                      )}
                    </div>
                    <div className="project-tile-text">
                      <div className="project-tile-title">{p.title}</div>
                      <div className="muted">{p.client_name || "—"}</div>
                      <div className="muted">Получено на сегодня: {toMoney(metrics?.received_to_date || 0)}</div>
                      <div className="muted">Потрачено по проекту: {toMoney(metrics?.spent_to_date || 0)}</div>
                    </div>
                  </div>
                </Link>
              )
            })}
            {filteredLeftProjects.length === 0 && <div className="muted">Совпадений не найдено</div>}
          </div>
        </div>

        <div className="panel">
          <div className="table-wrap">
            <table className="table overview-table">
              <colgroup>
                <col style={{ width: "220px" }} />
                <col style={{ width: "120px" }} />
                <col style={{ width: "120px" }} />
                <col style={{ width: "120px" }} />
                <col style={{ width: "120px" }} />
                <col style={{ width: "140px" }} />
                <col style={{ width: "120px" }} />
              </colgroup>
              <thead>
                <tr>
                  <th>Проект</th>
                  <th>Получено</th>
                  <th>Потрачено</th>
                  <th>Агентские</th>
                  <th>Доп прибыль</th>
                  <th>Всего в кармане</th>
                  <th>Баланс</th>
                </tr>
              </thead>
              <tbody>
                {filteredSnapshotProjects.map((p) => (
                  <tr key={p.project_id}>
                    <td><Link to={`/projects/${p.project_id}`}>{p.title}</Link></td>
                    <td>{toMoney(p.received_to_date)}</td>
                    <td>{toMoney(p.spent_to_date)}</td>
                    <td>{toMoney(p.agency_fee_to_date)}</td>
                    <td>{toMoney(p.extra_profit_to_date)}</td>
                    <td>{toMoney(p.in_pocket_to_date)}</td>
                    <td className={p.balance_to_date >= 0 ? "ok" : "bad"}>{toMoney(p.balance_to_date)}</td>
                  </tr>
                ))}
                {filteredSnapshotProjects.length === 0 && (
                  <tr>
                    <td colSpan={7} className="muted">Нет данных</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {error && (
        <div className="panel">
          <div className="muted" style={{ color: "#ff9a9a" }}>{error}</div>
        </div>
      )}
    </div>
    {createOpen && (
      <div
        className="modal-backdrop"
        onClick={() => {
          if (!creating) {
            setSearch((prev) => {
              const next = new URLSearchParams(prev)
              next.delete("create")
              return next
            })
          }
        }}
      >
        <form
          className="panel project-settings-panel project-settings-modal"
          onClick={(e) => e.stopPropagation()}
          onSubmit={(e) => {
            e.preventDefault()
            void createProject()
          }}
        >
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="h1">Добавить проект</div>
            <button
              type="button"
              className="btn icon-btn modal-close-btn"
              aria-label="Закрыть окно"
              disabled={creating}
              onClick={() => {
                setSearch((prev) => {
                  const next = new URLSearchParams(prev)
                  next.delete("create")
                  return next
                })
              }}
            >
              ×
            </button>
          </div>

          <div className="grid grid-2" style={{ marginTop: 10 }}>
            <input
              className="input"
              placeholder="Название проекта"
              value={form.title}
              autoFocus
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
            <button type="submit" className="btn" disabled={creating}>Сохранить</button>
          </div>
        </form>
      </div>
    )}
    {projectToDelete && (
      <div
        className="modal-backdrop"
        onClick={() => {
          if (!deletingProjectId) setProjectToDelete(null)
        }}
      >
        <div
          className="panel project-settings-panel project-delete-modal"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="h1">Удалить проект?</div>
          <div className="muted" style={{ marginTop: 8 }}>
            {`Проект «${projectToDelete.title}» будет удален без возможности восстановления.`}
          </div>
          <div className="row" style={{ justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
            <button
              type="button"
              className="btn"
              disabled={Boolean(deletingProjectId)}
              onClick={() => setProjectToDelete(null)}
            >
              Отмена
            </button>
            <button
              type="button"
              className="btn"
              disabled={Boolean(deletingProjectId)}
              onClick={() => {
                void deleteProjectConfirmed()
              }}
            >
              Удалить
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  )
}
