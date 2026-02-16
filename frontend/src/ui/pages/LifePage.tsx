import { useEffect, useRef, useState } from "react"
import { apiGet } from "../api"
import { openNativePicker } from "../datePicker"
import { formatNumberForInput, parseInputNumber } from "../numberInput"

type LifeProject = {
  project_id: number
  title: string
  organization?: string | null
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
  savings_total: number
  projects: LifeProject[]
}

function toMoney(v: number): string {
  return Number(v || 0).toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
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
  const [targetRaw, setTargetRaw] = useState("100 000")
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

  useEffect(() => {
    setError(null)
    void load(undefined, selectedMonth).catch((e) => setError(String(e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedMonth])

  return (
    <div className="grid">
      <div className="panel top-panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <div className="h1">Жизнь</div>
            <div className="timeline-current-row" style={{ marginTop: 8 }}>
              <button
                className="timeline-current-month"
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
          </div>
          <div className="row">
            <input
              className="input"
              style={{ width: 170 }}
              value={targetRaw}
              onChange={(e) => setTargetRaw(e.target.value)}
              onBlur={(e) => setTargetRaw(formatNumberForInput(e.currentTarget.value))}
              onKeyDown={(e) => {
                if (e.key !== "Enter") return
                e.preventDefault()
                const next = formatNumberForInput(e.currentTarget.value)
                setTargetRaw(next)
                void load(next, selectedMonth)
              }}
              placeholder="Сумма на жизнь"
            />
            <button className="btn" disabled={loading} onClick={() => void load()}>
              Пересчитать
            </button>
          </div>
        </div>
      </div>

      {data && (
        <>
          <div className="dashboard-strip">
            <div className="kpi-card">
              <div className="muted">Период</div>
              <div className="kpi-value">{data.period.label}</div>
            </div>
            <div className="kpi-card">
              <div className="muted">Цель на жизнь</div>
              <div className="kpi-value">{toMoney(data.target_amount)}</div>
            </div>
            <div className="kpi-card">
              <div className="muted">Покрыто</div>
              <div className="kpi-value ok">{toMoney(data.life_covered)}</div>
            </div>
            <div className="kpi-card">
              <div className="muted">В копилку</div>
              <div className="kpi-value accent">{toMoney(data.savings_total)}</div>
            </div>
          </div>

          {data.life_gap > 0 && (
            <div className="panel">
              <div className="muted" style={{ color: "#ffb0b0" }}>
                Не хватает на жизнь за период: {toMoney(data.life_gap)}
              </div>
            </div>
          )}

          <div className="panel">
            <div className="h1" style={{ marginBottom: 10 }}>Разбор по проектам</div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Проект</th>
                    <th>Организация</th>
                    <th>Получено за месяц</th>
                    <th>На жизнь</th>
                    <th>В копилку</th>
                  </tr>
                </thead>
                <tbody>
                  {data.projects.map((p) => (
                    <tr key={p.project_id}>
                      <td>{p.title}</td>
                      <td>{p.organization || "—"}</td>
                      <td>{toMoney(p.received_last_month)}</td>
                      <td>{toMoney(p.to_life)}</td>
                      <td>{toMoney(p.to_savings)}</td>
                    </tr>
                  ))}
                  {data.projects.length === 0 && (
                    <tr>
                      <td colSpan={5} className="muted">За выбранный месяц поступлений по проектам нет</td>
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
