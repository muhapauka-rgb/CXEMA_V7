import { useEffect, useState } from "react"
import { apiGet } from "../api"
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

export default function LifePage() {
  const [targetRaw, setTargetRaw] = useState("100 000")
  const [data, setData] = useState<LifeResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function load(sourceValue?: string) {
    const n = parseInputNumber(sourceValue ?? targetRaw)
    if (n == null || n < 0) {
      setError("Сумма на жизнь должна быть неотрицательным числом")
      return
    }
    try {
      setError(null)
      setLoading(true)
      const out = await apiGet<LifeResponse>(`/api/life/previous-month?target_amount=${encodeURIComponent(n)}`)
      setData(out)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="grid">
      <div className="panel top-panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <div className="h1">Жизнь</div>
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
                void load(next)
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
                      <td colSpan={5} className="muted">За прошлый месяц поступлений по проектам нет</td>
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
