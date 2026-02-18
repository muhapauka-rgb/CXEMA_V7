import { useEffect, useRef, useState } from "react"
import { apiGet } from "../api"
import { openNativePicker } from "../datePicker"
import { formatNumberForInput, parseInputNumber } from "../numberInput"

type LifeProject = {
  project_id: number
  title: string
  organization?: string | null
  source_month_key: string
  source_month_label: string
  source_kind: "current" | "reserve"
  opening_balance: number
  inflow_in_source_month: number
  used_for_life: number
  closing_balance: number
  received_last_month: number
  to_life: number
  to_savings: number
}

type LifeResponse = {
  period: {
    month_start: string
    month_end: string
    label: string
  }
  target_amount: number
  life_covered: number
  life_gap: number
  reserve_used: number
  savings_total: number
  projects: LifeProject[]
}

const LIFE_TARGET_STORAGE_KEY = "cxema-v7:life-target"

function toMoney(v: number): string {
  return Number(v || 0).toLocaleString("ru-RU", { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function nextMonthKey(d: Date): string {
  const year = d.getMonth() === 11 ? d.getFullYear() + 1 : d.getFullYear()
  const month = d.getMonth() === 11 ? 1 : d.getMonth() + 2
  return `${year}-${String(month).padStart(2, "0")}`
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

export default function LifePage() {
  const [targetRaw, setTargetRaw] = useState(() => {
    try {
      const saved = window.localStorage.getItem(LIFE_TARGET_STORAGE_KEY)
      if (!saved) return "100 000"
      const formatted = formatNumberForInput(saved)
      return formatted || "100 000"
    } catch {
      return "100 000"
    }
  })
  const [selectedMonth, setSelectedMonth] = useState(nextMonthKey(new Date()))
  const [data, setData] = useState<LifeResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const monthPickerRef = useRef<HTMLInputElement | null>(null)

  async function load(sourceValue?: string, monthValue?: string) {
    const n = parseInputNumber(sourceValue ?? targetRaw)
    if (n == null || n < 0) {
      setError("Сумма на жизнь должна быть неотрицательным числом")
      return
    }
    const month = monthValue ?? selectedMonth
    try {
      setError(null)
      setLoading(true)
      const out = await apiGet<LifeResponse>(`/api/life/month?target_amount=${encodeURIComponent(n)}&month=${encodeURIComponent(month)}`)
      setData(out)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  function commitTarget(raw: string) {
    const formatted = formatNumberForInput(raw)
    const next = formatted || "0"
    const parsed = parseInputNumber(next)
    if (parsed == null || parsed < 0) {
      setError("Сумма на жизнь должна быть неотрицательным числом")
      return
    }
    setTargetRaw(next)
    try {
      window.localStorage.setItem(LIFE_TARGET_STORAGE_KEY, next)
    } catch {
      // ignore storage errors
    }
    void load(next, selectedMonth)
  }

  useEffect(() => {
    setError(null)
    void load(undefined, selectedMonth).catch((e) => setError(String(e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedMonth])

  return (
    <div className="grid">
      {data && (
        <>
          <div className="panel top-panel">
            <div className="dashboard-strip life-kpi-strip">
              <div className="kpi-card">
                <div className="muted">Период</div>
                <button
                  type="button"
                  className="kpi-value life-period-button"
                  onClick={() => openNativePicker(monthPickerRef.current, true)}
                >
                  {monthLabelRu(selectedMonth)}
                </button>
                <input
                  ref={monthPickerRef}
                  className="timeline-month-picker-hidden"
                  type="month"
                  value={selectedMonth}
                  onChange={(e) => setSelectedMonth(e.target.value)}
                />
              </div>
              <div className="kpi-card">
                <div className="muted">Цель на месяц</div>
                <input
                  className="kpi-value-input"
                  value={targetRaw}
                  onChange={(e) => setTargetRaw(e.target.value)}
                  onBlur={(e) => commitTarget(e.currentTarget.value)}
                  onKeyDown={(e) => {
                    if (e.key !== "Enter") return
                    e.preventDefault()
                    commitTarget(e.currentTarget.value)
                  }}
                  aria-label="Цель на месяц"
                />
              </div>
              <div className="kpi-card">
                <div className="muted">Покрыто</div>
                <div className="kpi-value ok">{toMoney(data.life_covered)}</div>
              </div>
              <div className="kpi-card">
                <div className="muted">Заначка</div>
                <div className="kpi-value">{toMoney(data.reserve_used)}</div>
              </div>
              <div className="kpi-card">
                <div className="muted">В копилку</div>
                <div className="kpi-value accent">{toMoney(data.savings_total)}</div>
              </div>
            </div>
          </div>

          {data.life_gap > 0 && (
            <div className="panel">
              <div style={{ color: "var(--text)" }}>
                Не хватает до цели: {toMoney(data.life_gap)}
              </div>
            </div>
          )}

          <div className="panel">
            <div className="h1" style={{ marginBottom: 10 }}>Разбор по проектам</div>
            <div className="table-wrap">
              <table className="table life-table">
                <thead>
                  <tr>
                    <th>Проект</th>
                    <th>Организация</th>
                    <th>Источник</th>
                    <th>Было в копилке</th>
                    <th>в т.ч. поступление прошлого месяца</th>
                    <th>Взято на жизнь</th>
                    <th>Остаток копилки</th>
                  </tr>
                </thead>
                <tbody>
                  {data.projects.map((p) => (
                    <tr key={`${p.project_id}-${p.source_month_key}-${p.source_kind}`}>
                      <td>{p.title}</td>
                      <td>{p.organization || "—"}</td>
                      <td>{`${p.source_month_label} (${p.source_kind === "current" ? "текущий" : "заначка"})`}</td>
                      <td>{toMoney(p.opening_balance)}</td>
                      <td>{p.source_kind === "reserve" ? "—" : toMoney(p.inflow_in_source_month)}</td>
                      <td>{toMoney(p.used_for_life)}</td>
                      <td>{toMoney(p.closing_balance)}</td>
                    </tr>
                  ))}
                  {data.projects.length === 0 && (
                    <tr>
                      <td colSpan={7} className="muted">За выбранный месяц источников для жизни нет</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {error && (
        <div className="panel">
          <div className="muted" style={{ color: "#ff9a9a" }}>{error}</div>
        </div>
      )}
    </div>
  )
}
