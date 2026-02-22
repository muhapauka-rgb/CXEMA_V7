import { useEffect, useMemo, useState } from "react"
import { API_BASE, apiGet, apiPatch } from "../api"

type BackupFrequency = "OFF" | "DAILY" | "WEEKLY" | "MONTHLY"
type RestoreMode = "full" | "partial"

type AppSettings = {
  id: number
  usn_mode: "LEGAL" | "OPERATIONAL"
  usn_rate_percent: number
  backup_frequency: BackupFrequency
  last_backup_at?: string | null
  created_at: string
  updated_at: string
}

type BackupCopy = {
  name: string
  created_at: string
  size_bytes: number
}

type BackupCopiesOut = {
  retention_months: number
  copies: BackupCopy[]
  latest?: BackupCopy | null
}

type CopyProject = {
  id: number
  title: string
  organization?: string
}

type CopyProjectsOut = {
  copy_name: string
  projects: CopyProject[]
}

type RestorePreview = {
  copy_name: string
  mode: RestoreMode
  dry_run: boolean
  counts: Record<string, number>
  project_titles: string[]
  schema_version: number
}

type BackupPageProps = {
  asModal?: boolean
  onClose?: () => void
  embedded?: boolean
}

function formatBytes(bytes: number): string {
  const value = Number(bytes || 0)
  if (value < 1024) return `${value} Б`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} КБ`
  return `${(value / (1024 * 1024)).toFixed(1)} МБ`
}

function formatCopyLabel(copy: BackupCopy): string {
  const dt = new Date(copy.created_at)
  const date = Number.isNaN(dt.getTime()) ? copy.created_at : dt.toLocaleString("ru-RU")
  return `${date} (${formatBytes(copy.size_bytes)})`
}

export default function BackupPage({ asModal = false, onClose, embedded = false }: BackupPageProps) {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [backupFrequency, setBackupFrequency] = useState<BackupFrequency>("WEEKLY")
  const [savingFrequency, setSavingFrequency] = useState(false)

  const [copiesData, setCopiesData] = useState<BackupCopiesOut | null>(null)
  const [selectedCopy, setSelectedCopy] = useState<string>("")
  const [mode, setMode] = useState<RestoreMode>("full")
  const [copyProjects, setCopyProjects] = useState<CopyProject[]>([])
  const [projectFilter, setProjectFilter] = useState("")
  const [selectedProjectIds, setSelectedProjectIds] = useState<number[]>([])

  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void loadAll()
  }, [])

  useEffect(() => {
    if (!selectedCopy) {
      setCopyProjects([])
      setSelectedProjectIds([])
      return
    }
    void loadCopyProjects(selectedCopy)
  }, [selectedCopy])

  async function loadAll() {
    try {
      setError(null)
      const [settingsOut, copiesOut] = await Promise.all([
        apiGet<AppSettings>("/api/settings"),
        apiGet<BackupCopiesOut>("/api/backup/copies"),
      ])
      setSettings(settingsOut)
      setBackupFrequency(settingsOut.backup_frequency || "WEEKLY")
      setCopiesData(copiesOut)
      const latestName = copiesOut.latest?.name || copiesOut.copies[0]?.name || ""
      setSelectedCopy((prev) => prev || latestName)
    } catch (e) {
      setError(String(e))
    }
  }

  async function loadCopyProjects(copyName: string) {
    try {
      setError(null)
      const out = await apiGet<CopyProjectsOut>(`/api/backup/copies/${encodeURIComponent(copyName)}/projects`)
      setCopyProjects(out.projects || [])
      setSelectedProjectIds([])
    } catch (e) {
      setError(String(e))
      setCopyProjects([])
      setSelectedProjectIds([])
    }
  }

  async function handleFrequencyChange(next: BackupFrequency) {
    if (next === backupFrequency) return
    const prev = backupFrequency
    setBackupFrequency(next)
    try {
      setError(null)
      setSavingFrequency(true)
      const out = await apiPatch<AppSettings>("/api/settings", { backup_frequency: next })
      setSettings(out)
      setBackupFrequency(out.backup_frequency || next)
      setMsg("Частота бэкапа сохранена.")
    } catch (e) {
      setBackupFrequency(prev)
      setError(String(e))
    } finally {
      setSavingFrequency(false)
    }
  }

  async function exportBackup() {
    try {
      setError(null)
      setBusy(true)
      const res = await fetch(`${API_BASE}/api/backup/export`)
      if (!res.ok) throw new Error(await res.text())
      const blob = await res.blob()
      const contentDisposition = res.headers.get("Content-Disposition") || ""
      const m = /filename=\"([^\"]+)\"/.exec(contentDisposition)
      const filename = m?.[1] || `cxema-backup-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.zip`
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      setMsg("Бэкап выгружен.")
      await loadAll()
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function restore(copyName: string) {
    try {
      setError(null)
      setBusy(true)
      const params = new URLSearchParams({
        copy_name: copyName,
        mode,
        dry_run: "true",
      })
      if (mode === "partial") {
        if (!selectedProjectIds.length) {
          throw new Error("Выберите хотя бы один проект для частичного восстановления")
        }
        params.set("project_ids", selectedProjectIds.join(","))
      }

      const previewRes = await fetch(`${API_BASE}/api/backup/restore?${params.toString()}`, { method: "POST" })
      if (!previewRes.ok) throw new Error(await previewRes.text())
      const preview = (await previewRes.json()) as RestorePreview
      const projectsCount = Number(preview.counts?.projects || 0)
      const itemsCount = Number(preview.counts?.items || 0)
      if (!window.confirm(`Восстановление (${mode}). Проектов: ${projectsCount}, строк: ${itemsCount}. Продолжить?`)) {
        setMsg("Восстановление отменено.")
        return
      }

      params.set("dry_run", "false")
      const importRes = await fetch(`${API_BASE}/api/backup/restore?${params.toString()}`, { method: "POST" })
      if (!importRes.ok) throw new Error(await importRes.text())
      await importRes.json()
      setMsg("Восстановление завершено.")
      await loadAll()
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  const filteredProjects = useMemo(() => {
    const q = projectFilter.trim().toLowerCase()
    if (!q) return copyProjects
    return copyProjects.filter((p) => {
      const title = (p.title || "").toLowerCase()
      const org = (p.organization || "").toLowerCase()
      return title.includes(q) || org.includes(q)
    })
  }, [copyProjects, projectFilter])

  function toggleProject(id: number) {
    setSelectedProjectIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const latestLabel = copiesData?.latest ? formatCopyLabel(copiesData.latest) : "еще не создан"

  const body = (
    <div className="backup-modal-body">
      <div className="backup-section">
        <div className="backup-inline-actions">
          <button className="btn" onClick={() => void exportBackup()} disabled={busy}>Выгрузить базу</button>
          <button className="btn" onClick={() => void restore("latest")} disabled={busy || !copiesData?.latest}>Загрузить из последней копии</button>
        </div>
      </div>

      <div className="backup-section">
        <div className="backup-grid backup-grid-frequency">
          <label className="settings-field">
            <span className="settings-label">Частота бэкапа</span>
            <select
              className="input"
              value={backupFrequency}
              onChange={(e) => void handleFrequencyChange(e.target.value as BackupFrequency)}
              disabled={savingFrequency || busy}
            >
              <option value="OFF">Выключен</option>
              <option value="DAILY">Ежедневно</option>
              <option value="WEEKLY">Еженедельно</option>
              <option value="MONTHLY">Ежемесячно</option>
            </select>
          </label>
        </div>
      </div>

      <div className="backup-section">
        <div className="backup-grid backup-grid-restore">
          <label className="settings-field">
          <span className="settings-label">Выбрать копию для загрузки</span>
          <select className="input" value={selectedCopy} onChange={(e) => setSelectedCopy(e.target.value)} disabled={busy}>
            {copiesData?.copies?.length ? copiesData.copies.map((copy) => (
              <option key={copy.name} value={copy.name}>{formatCopyLabel(copy)}</option>
            )) : <option value="">Нет копий</option>}
          </select>
          </label>

          <label className="settings-field">
            <span className="settings-label">Режим восстановления</span>
            <select className="input" value={mode} onChange={(e) => setMode(e.target.value as RestoreMode)} disabled={busy}>
              <option value="full">Полное восстановление</option>
              <option value="partial">Частичное восстановление</option>
            </select>
          </label>

          <div className="backup-actions-cell">
            <button className="btn" onClick={() => void restore(selectedCopy)} disabled={busy || !selectedCopy}>Загрузить выбранную копию</button>
          </div>
        </div>
      </div>

      {mode === "partial" && (
        <div className="backup-section">
          <div className="backup-section-title">Проекты для частичного восстановления</div>
          <div className="backup-grid">
            <input
              className="input"
              placeholder="Фильтр по названию проекта или организации"
              value={projectFilter}
              onChange={(e) => setProjectFilter(e.target.value)}
            />
            <div className="backup-inline-actions">
              <button
                className="btn"
                type="button"
                onClick={() => setSelectedProjectIds(filteredProjects.map((p) => p.id))}
                disabled={!filteredProjects.length}
              >
                Выбрать отфильтрованные
              </button>
              <button className="btn" type="button" onClick={() => setSelectedProjectIds([])}>Очистить выбор</button>
            </div>
            <div className="table-wrap backup-projects-wrap">
              <table className="table backup-projects-table">
                <thead>
                  <tr>
                    <th className="backup-col-select">Выбор</th>
                    <th>Проект</th>
                    <th>Организация</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredProjects.map((p) => (
                    <tr key={p.id}>
                      <td className="backup-col-select">
                        <input
                          type="checkbox"
                          checked={selectedProjectIds.includes(p.id)}
                          onChange={() => toggleProject(p.id)}
                        />
                      </td>
                      <td>{p.title}</td>
                      <td>{p.organization || "—"}</td>
                    </tr>
                  ))}
                  {!filteredProjects.length && (
                    <tr>
                      <td colSpan={3} className="muted">Проекты не найдены</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      <div className="backup-meta muted">
        Копии хранятся {copiesData?.retention_months ?? 4} месяца. Последний бэкап: {settings?.last_backup_at ? new Date(settings.last_backup_at).toLocaleString("ru-RU") : "еще не создан"}.
        Последняя копия: {latestLabel}.
      </div>

      {msg && <div className="backup-status ok">{msg}</div>}
      {error && <div className="backup-status bad">{error}</div>}
    </div>
  )

  if (asModal) {
    return (
      <div className="grid">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="h1">Бэкап</div>
          <button className="btn icon-btn modal-close-btn" aria-label="Закрыть окно" onClick={onClose}>×</button>
        </div>
        {body}
      </div>
    )
  }
  if (embedded) {
    return <>{body}</>
  }
  return <div className="card">{body}</div>
}
