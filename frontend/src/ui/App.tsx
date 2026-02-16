import { NavLink, Route, Routes } from 'react-router-dom'
import OverviewPage from './pages/OverviewPage'
import ProjectsPage from './pages/ProjectsPage'
import ProjectPage from './pages/ProjectPage'

export default function App() {
  return (
    <>
      <div className="nav">
        <div className="brand">CXEMA V7</div>
        <NavLink to="/" className="btn">Итоги</NavLink>
        <NavLink to="/projects" className="btn">Проекты</NavLink>
      </div>

      <div className="container">
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectPage />} />
        </Routes>
      </div>
    </>
  )
}
