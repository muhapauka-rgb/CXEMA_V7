import { Link, NavLink, Route, Routes } from 'react-router-dom'
import OverviewPage from './pages/OverviewPage'
import ProjectPage from './pages/ProjectPage'
import SettingsPage from './pages/SettingsPage'
import LifePage from './pages/LifePage'

function GearIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path
        d="M19.4 13.5c.04-.33.1-.67.1-1s-.06-.67-.1-1l2.12-1.66a.52.52 0 0 0 .12-.65l-2-3.46a.5.5 0 0 0-.6-.22l-2.49 1a7.23 7.23 0 0 0-1.73-1l-.38-2.65A.5.5 0 0 0 14 2h-4a.5.5 0 0 0-.49.42l-.38 2.65c-.62.25-1.2.58-1.73 1l-2.49-1a.5.5 0 0 0-.6.22l-2 3.46a.5.5 0 0 0 .12.65L4.6 11.5c-.04.33-.1.67-.1 1s.06.67.1 1L2.48 15.16a.52.52 0 0 0-.12.65l2 3.46a.5.5 0 0 0 .6.22l2.49-1c.53.42 1.11.76 1.73 1l.38 2.65A.5.5 0 0 0 10 22h4a.5.5 0 0 0 .49-.42l.38-2.65c.62-.25 1.2-.58 1.73-1l2.49 1a.5.5 0 0 0 .6-.22l2-3.46a.5.5 0 0 0-.12-.65l-2.17-1.1ZM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8Z"
      />
    </svg>
  )
}

export default function App() {
  const navClass = ({ isActive }: { isActive: boolean }) => `btn nav-link${isActive ? " active" : ""}`

  return (
    <>
      <div className="nav">
        <div className="brand">CXEMA V7</div>
        <NavLink to="/" className={navClass}>Проекты</NavLink>
        <NavLink to="/life" className={navClass}>Жизнь</NavLink>
        <Link to="/?create=1" className="btn nav-add">+ Проект</Link>
        <NavLink to="/settings" className={({ isActive }) => `btn nav-link nav-gear${isActive ? " active" : ""}`} aria-label="Настройки">
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
    </>
  )
}
