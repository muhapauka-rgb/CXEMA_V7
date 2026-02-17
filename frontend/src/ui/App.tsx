import { useEffect, useState } from 'react'
import { Link, NavLink, Route, Routes } from 'react-router-dom'
import OverviewPage from './pages/OverviewPage'
import ProjectPage from './pages/ProjectPage'
import SettingsPage from './pages/SettingsPage'
import LifePage from './pages/LifePage'

type ThemeMode = "dark" | "light"

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
      <path d="M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Z" />
      <path d="M19.4 12a7.6 7.6 0 0 0-.1-1.1l2-1.6-2-3.5-2.4 1a7.7 7.7 0 0 0-1.9-1.1l-.4-2.5H9.4L9 5.7c-.7.2-1.3.6-1.9 1.1l-2.4-1-2 3.5 2 1.6c-.1.4-.1.7-.1 1.1s0 .7.1 1.1l-2 1.6 2 3.5 2.4-1c.6.5 1.2.9 1.9 1.1l.4 2.5h5.2l.4-2.5c.7-.2 1.3-.6 1.9-1.1l2.4 1 2-3.5-2-1.6c.1-.4.1-.7.1-1.1Z" />
    </svg>
  )
}

function ThemeIcon({ theme }: { theme: ThemeMode }) {
  if (theme === "light") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 3v2.2M12 18.8V21M4.2 12H3M21 12h-1.2M6.1 6.1 4.6 4.6M19.4 19.4l-1.5-1.5M17.9 6.1l1.5-1.5M4.6 19.4l1.5-1.5" />
        <circle cx="12" cy="12" r="4.2" />
      </svg>
    )
  }

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M21 12.8A7.4 7.4 0 0 1 11.2 3a6.8 6.8 0 1 0 9.8 9.8Z" />
    </svg>
  )
}

function AccentIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3c4.9 0 9 3.6 9 8.2 0 2.7-1.5 4.3-3.4 5.3-1.2.6-1.8 1.7-1.8 3v.7H8.2v-.7c0-1.3-.6-2.4-1.8-3C4.5 15.5 3 13.9 3 11.2 3 6.6 7.1 3 12 3Z" />
      <path d="M9 21h6" />
    </svg>
  )
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
  const [isAccentOpen, setIsAccentOpen] = useState(false)
  const [accentInput, setAccentInput] = useState(accent)

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
    if (!isAccentOpen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsAccentOpen(false)
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [isAccentOpen])

  function toggleTheme() {
    setTheme((prev) => (prev === "light" ? "dark" : "light"))
  }

  function applyAccent(value: string) {
    const next = normalizeHexColor(value)
    setAccentInput(value)
    if (next) setAccent(next)
  }

  return (
    <>
      <div className={isAccentOpen ? "page-content-muted" : ""}>
        <div className="nav">
          <div className="brand">CXEMA <span className="v7">V7</span></div>
          <NavLink to="/" className={navClass}>Проекты</NavLink>
          <NavLink to="/life" className={navClass}>Жизнь</NavLink>
          <Link to="/?create=1" className="btn cta nav-add">+ Проект</Link>
          <button className="btn icon-btn icon-stroke" onClick={toggleTheme} aria-label="Тема" title="Тема">
            <ThemeIcon theme={theme} />
          </button>
          <button className="btn icon-btn icon-stroke" onClick={() => setIsAccentOpen(true)} aria-label="Акцент" title="Акцент">
            <AccentIcon />
          </button>
          <NavLink to="/settings" className={({ isActive }) => `btn nav-link nav-gear icon-stroke${isActive ? " active" : ""}`} aria-label="Настройки">
            <GearIcon />
          </NavLink>
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

      {isAccentOpen && (
        <div
          className="modal-backdrop"
          onClick={() => setIsAccentOpen(false)}
        >
          <div className="panel project-settings-panel project-settings-modal accent-modal" onClick={(e) => e.stopPropagation()}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div className="h1">Акцентный цвет</div>
              <button className="btn" onClick={() => setIsAccentOpen(false)}>Закрыть</button>
            </div>

            <div className="row" style={{ marginTop: 12, alignItems: "center" }}>
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
      )}
    </>
  )
}
