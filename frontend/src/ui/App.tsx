import { useEffect, useState } from 'react'
import { Link, NavLink, Route, Routes } from 'react-router-dom'
import OverviewPage from './pages/OverviewPage'
import ProjectPage from './pages/ProjectPage'
import SettingsPage from './pages/SettingsPage'
import LifePage from './pages/LifePage'
import { API_BASE, apiGet } from './api'

type ThemeMode = "dark" | "light"

type DiscountEntry = {
  project_id: number
  project_title: string
  organization?: string | null
  item_id: number
  item_title: string
  item_date?: string | null
  discount_amount: number
}

type DiscountCounterparty = {
  organization: string
  discount_total: number
}

type DiscountSummary = {
  as_of: string
  total_discount: number
  entries: DiscountEntry[]
  counterparties: DiscountCounterparty[]
}

const THEME_STORAGE_KEY = "cxema_theme"
const ACCENT_STORAGE_KEY = "cxema_accent"
const DEFAULT_ACCENT = "#ff2da1"

function normalizeHexColor(value: string): string | null {
  const text = value.trim()
  if (!/^#[0-9a-fA-F]{6}$/.test(text)) return null
  return text.toLowerCase()
}

function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M19.4 13.5c.04-.33.1-.67.1-1s-.06-.67-.1-1l2.12-1.66a.52.52 0 0 0 .12-.65l-2-3.46a.5.5 0 0 0-.6-.22l-2.49 1a7.23 7.23 0 0 0-1.73-1l-.38-2.65A.5.5 0 0 0 14 2h-4a.5.5 0 0 0-.49.42l-.38 2.65c-.62.25-1.2.58-1.73 1l-2.49-1a.5.5 0 0 0-.6.22l-2 3.46a.5.5 0 0 0 .12.65L4.6 11.5c-.04.33-.1.67-.1 1s.06.67.1 1L2.48 15.16a.52.52 0 0 0-.12.65l2 3.46a.5.5 0 0 0 .6.22l2.49-1c.53.42 1.11.76 1.73 1l.38 2.65A.5.5 0 0 0 10 22h4a.5.5 0 0 0 .49-.42l.38-2.65c.62-.25 1.2-.58 1.73-1l2.49 1a.5.5 0 0 0 .6-.22l2-3.46a.5.5 0 0 0-.12-.65l-2.17-1.1ZM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8Z" />
    </svg>
  )
}

function VisualSettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 7h18" />
      <path d="M3 17h18" />
      <circle cx="8" cy="7" r="3" />
      <circle cx="16" cy="17" r="3" />
    </svg>
  )
}

function ExportRegistryIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 10v7a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2v-7" />
      <path d="M12 15V4" />
      <path d="m8.8 7.2 3.2-3.2 3.2 3.2" />
    </svg>
  )
}

function CxemaWordmark() {
  return (
    <svg className="brand-logo" viewBox="24 0 288 70" aria-hidden="true">
      <g transform="translate(-34 0)">
        <path d="M58 12a24 24 0 1 0 0 46" />
        <path d="M84 14 148 56" />
        <path d="M148 14 84 56" />
        <path d="M164 12v46M164 12h52M164 35h46M164 58h52" />
        <path d="M232 58V12l24 40 24-40v46" />
        <path d="M298 58 322 12l24 46M308 39h28" />
      </g>
    </svg>
  )
}

function fmtSignedInt(value: number): string {
  const num = Number(value || 0)
  if (!Number.isFinite(num) || num === 0) return "0"
  const abs = Math.abs(num).toLocaleString("ru-RU", { minimumFractionDigits: 0, maximumFractionDigits: 0 })
  return num > 0 ? `+${abs}` : `-${abs}`
}

export default function App() {
  const navClass = ({ isActive }: { isActive: boolean }) => `btn nav-link${isActive ? " active" : ""}`
  const [theme, setTheme] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem(THEME_STORAGE_KEY)
    if (saved === "dark" || saved === "light") return saved
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) return "light"
    return "dark"
  })
  const [accent, setAccent] = useState<string>(() => {
    const saved = localStorage.getItem(ACCENT_STORAGE_KEY)
    return normalizeHexColor(saved || "") || DEFAULT_ACCENT
  })
  const [isVisualOpen, setIsVisualOpen] = useState(false)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const [accentInput, setAccentInput] = useState(accent)
  const [isDiscountsOpen, setIsDiscountsOpen] = useState(false)
  const [isExportingRegistry, setIsExportingRegistry] = useState(false)
  const [discountsAsOf, setDiscountsAsOf] = useState(() => new Date().toISOString().slice(0, 10))
  const [discountsData, setDiscountsData] = useState<DiscountSummary | null>(null)
  const [discountsLoading, setDiscountsLoading] = useState(false)
  const [discountsError, setDiscountsError] = useState<string | null>(null)

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme)
    localStorage.setItem(THEME_STORAGE_KEY, theme)
  }, [theme])

  useEffect(() => {
    document.documentElement.style.setProperty("--accent", accent)
    localStorage.setItem(ACCENT_STORAGE_KEY, accent)
    setAccentInput(accent)
  }, [accent])

  useEffect(() => {
    if (!isVisualOpen && !isDiscountsOpen && !isSettingsOpen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsVisualOpen(false)
        setIsDiscountsOpen(false)
        setIsSettingsOpen(false)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [isVisualOpen, isDiscountsOpen, isSettingsOpen])

  async function loadDiscounts(asOf = discountsAsOf) {
    try {
      setDiscountsError(null)
      setDiscountsLoading(true)
      const out = await apiGet<DiscountSummary>(`/api/discounts/summary?as_of=${encodeURIComponent(asOf)}`)
      setDiscountsData(out)
    } catch (e) {
      setDiscountsError(String(e))
    } finally {
      setDiscountsLoading(false)
    }
  }

  function applyAccent(value: string) {
    const next = normalizeHexColor(value)
    setAccentInput(value)
    if (next) setAccent(next)
  }

  async function exportRegistryExcel() {
    try {
      setIsExportingRegistry(true)
      const res = await fetch(`${API_BASE}/api/exports/excel`)
      if (!res.ok) throw new Error(await res.text())
      const blob = await res.blob()
      const contentDisposition = res.headers.get("Content-Disposition") || ""
      const m = /filename=\"([^\"]+)\"/.exec(contentDisposition)
      const filename = m?.[1] || `cxema-registry-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.xlsx`
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      const msg = String(e)
      window.alert(`Не удалось выгрузить Excel: ${msg}`)
    } finally {
      setIsExportingRegistry(false)
    }
  }

  return (
    <>
      <div className={isVisualOpen || isDiscountsOpen || isSettingsOpen ? "page-content-muted" : ""}>
        <div className="nav">
          <div className="brand"><CxemaWordmark /> <span className="v7">V7</span></div>
          <NavLink to="/" className={navClass}>Проекты</NavLink>
          <NavLink to="/life" className={navClass}>Жизнь</NavLink>
          <Link to="/?create=1" className="btn cta nav-add">+ Проект</Link>
          <button
            className="btn"
            onClick={() => {
              setIsVisualOpen(false)
              setIsSettingsOpen(false)
              setIsDiscountsOpen(true)
              void loadDiscounts(discountsAsOf)
            }}
          >
            Скидки
          </button>
          <button
            className="btn icon-btn icon-stroke"
            aria-label="Выгрузить сводную базу в Excel"
            onClick={() => void exportRegistryExcel()}
            disabled={isExportingRegistry}
            title="Выгрузить базу в Excel"
          >
            <ExportRegistryIcon />
          </button>
          <button className="btn icon-btn icon-stroke" onClick={() => setIsVisualOpen(true)} aria-label="Визуализация">
            <VisualSettingsIcon />
          </button>
          <button
            className="btn icon-btn settings-icon-btn"
            aria-label="Настройки"
            onClick={() => {
              setIsVisualOpen(false)
              setIsDiscountsOpen(false)
              setIsSettingsOpen(true)
            }}
          >
            <GearIcon />
          </button>
        </div>

        <div className="container">
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/projects" element={<OverviewPage />} />
            <Route path="/life" element={<LifePage />} />
            <Route path="/projects/:id" element={<ProjectPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </div>
      </div>

      {isVisualOpen && (
        <div
          className="modal-backdrop"
          onClick={() => setIsVisualOpen(false)}
        >
          <div className="panel project-settings-panel project-settings-modal accent-modal" onClick={(e) => e.stopPropagation()}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div className="h1">Визуализация</div>
              <button className="btn icon-btn modal-close-btn" aria-label="Закрыть окно" onClick={() => setIsVisualOpen(false)}>×</button>
            </div>

            <div className="grid" style={{ marginTop: 12 }}>
              <div className="muted" style={{ color: "var(--text)", fontWeight: 700 }}>Тема</div>
              <div className="row">
                <button className={`btn ${theme === "dark" ? "tab-active" : ""}`} onClick={() => setTheme("dark")}>Черная</button>
                <button className={`btn ${theme === "light" ? "tab-active" : ""}`} onClick={() => setTheme("light")}>Белая</button>
              </div>

              <div className="muted" style={{ color: "var(--text)", fontWeight: 700 }}>Акцент</div>
              <div className="row" style={{ alignItems: "center" }}>
                <input
                  className="input accent-color-input"
                  type="color"
                  value={normalizeHexColor(accentInput) || accent}
                  onChange={(e) => applyAccent(e.target.value)}
                />
                <input
                  className="input accent-hex-input"
                  value={accentInput}
                  onChange={(e) => applyAccent(e.target.value)}
                />
                <button className="btn" onClick={() => setAccent(DEFAULT_ACCENT)}>Сброс</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {isSettingsOpen && (
        <div
          className="modal-backdrop"
          onClick={() => setIsSettingsOpen(false)}
        >
          <div className="panel project-settings-panel project-settings-modal" onClick={(e) => e.stopPropagation()}>
            <SettingsPage asModal onClose={() => setIsSettingsOpen(false)} />
          </div>
        </div>
      )}

      {isDiscountsOpen && (
        <div
          className="modal-backdrop"
          onClick={() => setIsDiscountsOpen(false)}
        >
          <div className="panel project-settings-panel project-settings-modal discounts-modal" onClick={(e) => e.stopPropagation()}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div className="h1">Скидки</div>
              <button className="btn icon-btn modal-close-btn" aria-label="Закрыть окно" onClick={() => setIsDiscountsOpen(false)}>×</button>
            </div>

            <div className="row" style={{ marginTop: 10 }}>
              <label className="settings-field" style={{ maxWidth: 180 }}>
                <span className="settings-label">Дата среза</span>
                <input
                  className="input"
                  type="date"
                  value={discountsAsOf}
                  onChange={(e) => setDiscountsAsOf(e.target.value)}
                />
              </label>
              <button className="btn" onClick={() => void loadDiscounts(discountsAsOf)}>Обновить</button>
            </div>

            {discountsLoading && <div className="muted">Загрузка…</div>}
            {discountsError && <div className="muted bad">{discountsError}</div>}

            {discountsData && !discountsLoading && (
              <div className="grid" style={{ marginTop: 4 }}>
                <div className="dashboard-strip discounts-kpi-strip">
                  <div className="kpi-card">
                    <div className="muted">Итого скидок</div>
                    <div className={`kpi-value ${discountsData.total_discount > 0 ? "accent" : discountsData.total_discount < 0 ? "ok" : ""}`}>
                      {fmtSignedInt(discountsData.total_discount)}
                    </div>
                  </div>
                  <div className="kpi-card">
                    <div className="muted">Контрагентов</div>
                    <div className="kpi-value">{discountsData.counterparties.length}</div>
                  </div>
                  <div className="kpi-card">
                    <div className="muted">Позиции</div>
                    <div className="kpi-value">{discountsData.entries.length}</div>
                  </div>
                </div>

                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Организация</th>
                        <th>Сальдо скидок</th>
                      </tr>
                    </thead>
                    <tbody>
                      {discountsData.counterparties.map((row) => (
                        <tr key={row.organization}>
                          <td>{row.organization}</td>
                          <td className={row.discount_total > 0 ? "accent" : row.discount_total < 0 ? "ok" : ""}>
                            {fmtSignedInt(row.discount_total)}
                          </td>
                        </tr>
                      ))}
                      {discountsData.counterparties.length === 0 && (
                        <tr>
                          <td colSpan={2} className="muted">Скидок на выбранную дату нет</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Проект</th>
                        <th>Организация</th>
                        <th>Позиция</th>
                        <th>Дата</th>
                        <th>Скидка</th>
                      </tr>
                    </thead>
                    <tbody>
                      {discountsData.entries.map((row) => (
                        <tr key={`${row.project_id}-${row.item_id}`}>
                          <td>{row.project_title}</td>
                          <td>{row.organization || "—"}</td>
                          <td>{row.item_title}</td>
                          <td>{row.item_date || "—"}</td>
                          <td className={row.discount_amount > 0 ? "accent" : row.discount_amount < 0 ? "ok" : ""}>
                            {fmtSignedInt(row.discount_amount)}
                          </td>
                        </tr>
                      ))}
                      {discountsData.entries.length === 0 && (
                        <tr>
                          <td colSpan={5} className="muted">Позиции со скидкой на выбранную дату не найдены</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                <div className="muted">Знак: <b>+</b> дали скидку клиенту, <b>-</b> получили скидку в нашу пользу.</div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
