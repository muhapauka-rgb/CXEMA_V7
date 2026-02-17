import { useEffect, useMemo, useRef, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { apiGet, apiPost } from "../api"
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
  const today = new Date()
  const m = parseMonthKey(selected)
  const monthEnd = new Date(m.getFullYear(), m.getMonth() + 1, 0)
  const at = monthEnd > today ? today : monthEnd
  const z = (n: number) => String(n).padStart(2, "0")
  return `${at.getFullYear()}-${z(at.getMonth() + 1)}-${z(at.getDate())}`
}

function RefreshIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
      <path d="M21 3v6h-6" />
    </svg>
  )
}

function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M19.4 13.5c.04-.33.1-.67.1-1s-.06-.67-.1-1l2.12-1.66a.52.52 0 0 0 .12-.65l-2-3.46a.5.5 0 0 0-.6-.22l-2.49 1a7.23 7.23 0 0 0-1.73-1l-.38-2.65A.5.5 0 0 0 14 2h-4a.5.5 0 0 0-.49.42l-.38 2.65c-.62.25-1.2.58-1.73 1l-2.49-1a.5.5 0 0 0-.6.22l-2 3.46a.5.5 0 0 0 .12.65L4.6 11.5c-.04.33-.1.67-.1 1s.06.67.1 1L2.48 15.16a.52.52 0 0 0-.12.65l2 3.46a.5.5 0 0 0 .6.22l2.49-1c.53.42 1.11.76 1.73 1l.38 2.65A.5.5 0 0 0 10 22h4a.5.5 0 0 0 .49-.42l.38-2.65c.62-.25 1.2-.58 1.73-1l2.49 1a.5.5 0 0 0 .6-.22l2-3.46a.5.5 0 0 0-.12-.65l-2.17-1.1ZM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8Z" />
    </svg>
  )
}

export default function OverviewPage() {
  const [search, setSearch] = useSearchParams()
  const [snapshot, setSnapshot] = useState<OverviewSnapshot | null>(null)
  const [projectsMeta, setProjectsMeta] = useState<ProjectMeta[]>([])
  const [months, setMonths] = useState<string[]>([monthKey(new Date())])
  const [selectedMonth, setSelectedMonth] = useState(monthKey(new Date()))
  const [form, setForm] = useState<CreateProjectForm>(EMPTY_FORM)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const monthPickerRef = useRef<HTMLInputElement | null>(null)

  const createOpen = search.get("create") === "1"
  const at = useMemo(() => snapshotAtFromMonth(selectedMonth), [selectedMonth])
  const selectedIdx = Math.max(0, months.indexOf(selectedMonth))
  const metaById = useMemo(() => new Map(projectsMeta.map((p) => [p.id, p])), [projectsMeta])

  async function loadProjectsMeta() {
    const data = await apiGet<ProjectMeta[]>("/api/projects")
    setProjectsMeta(data)
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
      await apiPost("/api/projects", {
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
      await loadAll()
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
      <div className="panel top-panel top-panel-sticky">
        <div className="timeline-panel">
          <div className="timeline-head">
            <button
              className="timeline-current-month"
              onClick={() => openNativePicker(monthPickerRef.current, true)}
            >
              {monthLabelRu(selectedMonth)}
            </button>
            <div className="row timeline-actions">
              <button className="btn icon-btn icon-stroke" aria-label="Обновить" title="Обновить" onClick={() => void loadAll()}>
                <RefreshIcon />
              </button>
              <Link className="btn icon-btn settings-icon-btn" to="/settings" aria-label="Глобальные настройки" title="Глобальные настройки">
                <GearIcon />
              </Link>
            </div>
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

      <div className="classic-layout">
        <div className="panel">
          <div className="grid">
            {(snapshot?.projects || []).map((p) => {
              const meta = metaById.get(p.project_id)
              return (
                <Link key={p.project_id} to={`/projects/${p.project_id}`} className="project-tile">
                  <div className="project-tile-title">{p.title}</div>
                  <div className="muted">{meta?.client_name || "—"}</div>
                  <div className="muted">Получено на сегодня: {toMoney(p.received_to_date)}</div>
                  <div className="muted">Потрачено по проекту: {toMoney(p.spent_to_date)}</div>
                </Link>
              )
            })}
            {(snapshot?.projects || []).length === 0 && <div className="muted">На выбранный месяц активных проектов нет</div>}
          </div>
        </div>

        <div className="panel">
          <div className="table-wrap">
            <table className="table overview-table">
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
                {(snapshot?.projects || []).map((p) => (
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
                {(snapshot?.projects || []).length === 0 && (
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
              className="btn"
              disabled={creating}
              onClick={() => {
                setSearch((prev) => {
                  const next = new URLSearchParams(prev)
                  next.delete("create")
                  return next
                })
              }}
            >
              Закрыть
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
    </>
  )
}
