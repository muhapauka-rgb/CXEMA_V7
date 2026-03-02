import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { API_BASE, apiGet, apiPatch } from "../api"
import BackupPage from "./BackupPage"

type GoogleAuthStatus = {
  mode: string
  connected: boolean
  client_secret_configured: boolean
  redirect_uri: string
  token_file_path: string
  last_error?: string | null
}

type GoogleAuthStart = {
  auth_url: string
  state: string
}

type AppSettings = {
  id: number
  usn_mode: "LEGAL" | "OPERATIONAL"
  usn_rate_percent: number
  created_at: string
  updated_at: string
}

type RollingBackupStatus = {
  mode: string
  db_path: string
  backup_dir: string
  days: string
  time: string
  launch_agent: { exists: boolean; path: string; size_bytes: number; updated_at?: string | null }
  current: { exists: boolean; path: string; size_bytes: number; updated_at?: string | null }
  prev: { exists: boolean; path: string; size_bytes: number; updated_at?: string | null }
}

type SettingsPageProps = {
  asModal?: boolean
  onClose?: () => void
}

export default function SettingsPage({ asModal = false, onClose }: SettingsPageProps) {
  const [status, setStatus] = useState<GoogleAuthStatus | null>(null)
  const [usnMode, setUsnMode] = useState<"LEGAL" | "OPERATIONAL">("OPERATIONAL")
  const [usnRateRaw, setUsnRateRaw] = useState("6")
  const [savingTax, setSavingTax] = useState(false)
  const [isBackupOpen, setIsBackupOpen] = useState(false)
  const [isExportingRegistry, setIsExportingRegistry] = useState(false)
  const [isUpdatingApp, setIsUpdatingApp] = useState(false)
  const [rollingBackup, setRollingBackup] = useState<RollingBackupStatus | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const RELEASES_URL = "https://github.com/ponch/CXEMA_V7/releases"

  useEffect(() => {
    void loadAll()
  }, [])

  async function loadAll() {
    try {
      setError(null)
      const [googleStatus, settings] = await Promise.all([
        apiGet<GoogleAuthStatus>("/api/google/auth/status"),
        apiGet<AppSettings>("/api/settings"),
      ])
      setStatus(googleStatus)
      setUsnMode(settings.usn_mode)
      setUsnRateRaw(String(settings.usn_rate_percent))
      try {
        const backupStatus = await apiGet<RollingBackupStatus>("/api/backup/rolling-status")
        setRollingBackup(backupStatus)
      } catch {
        setRollingBackup(null)
      }
    } catch (e) {
      setError(String(e))
    }
  }

  async function refreshStatus() {
    try {
      setError(null)
      const data = await apiGet<GoogleAuthStatus>("/api/google/auth/status")
      setStatus(data)
    } catch (e) {
      setError(String(e))
    }
  }

  async function startOauth() {
    try {
      setError(null)
      const out = await apiGet<GoogleAuthStart>("/api/google/auth/start")
      window.open(out.auth_url, "_blank", "noopener,noreferrer")
      setMsg("Открыто окно Google OAuth. После завершения нажми «Проверить подключение».")
    } catch (e) {
      setError(String(e))
    }
  }

  async function saveTaxSettings() {
    const parsedRate = Number(usnRateRaw.replace(",", "."))
    if (!Number.isFinite(parsedRate) || parsedRate < 0) {
      setError("Ставка УСН должна быть неотрицательным числом")
      return
    }
    try {
      setError(null)
      setSavingTax(true)
      const updated = await apiPatch<AppSettings>("/api/settings", {
        usn_mode: usnMode,
        usn_rate_percent: parsedRate,
      })
      setUsnMode(updated.usn_mode)
      setUsnRateRaw(String(updated.usn_rate_percent))
      setMsg("Налоговые настройки сохранены.")
    } catch (e) {
      setError(String(e))
    } finally {
      setSavingTax(false)
    }
  }

  async function exportRegistryExcel() {
    try {
      setError(null)
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
      setMsg("База выгружена.")
    } catch (e) {
      setError(String(e))
    } finally {
      setIsExportingRegistry(false)
    }
  }

  async function openUpdatesPage() {
    if (window.cxemaDesktop?.runUpdate) {
      try {
        setError(null)
        setIsUpdatingApp(true)
        await window.cxemaDesktop.runUpdate()
        setMsg("Открыт установщик обновления. Подтверди шаги в открывшемся окне.")
      } catch (e) {
        setError(String(e))
      } finally {
        setIsUpdatingApp(false)
      }
      return
    }
    window.open(RELEASES_URL, "_blank", "noopener,noreferrer")
    setMsg("Открыта страница обновлений. Скачай свежую версию и установи поверх текущей.")
  }

  const settingsBody = (
    <div className="settings-modal-layout">
      <section className="settings-section-block">
        <div className="settings-section-title">Google</div>
        <div className="row settings-actions-row">
          <button className="btn" onClick={() => void refreshStatus()}>Проверить подключение</button>
          <button className="btn" onClick={() => void startOauth()}>Подключить Google (OAuth)</button>
        </div>
        <div className="settings-inline-note">
          Подключение Google: {status?.connected ? "да" : "нет"}
        </div>
      </section>

      <section className="settings-section-block">
        <div className="settings-section-title">Налоги</div>
        <div className="row settings-actions-row">
          <button
            className={`btn ${usnMode === "LEGAL" ? "tab-active" : ""}`}
            onClick={() => setUsnMode("LEGAL")}
            disabled={savingTax}
          >
            Юридическая
          </button>
          <button
            className={`btn ${usnMode === "OPERATIONAL" ? "tab-active" : ""}`}
            onClick={() => setUsnMode("OPERATIONAL")}
            disabled={savingTax}
          >
            Операционная
          </button>
        </div>
        <div className="settings-tax-row">
          <input
            className="input"
            placeholder="Ставка УСН, %"
            value={usnRateRaw}
            onChange={(e) => setUsnRateRaw(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return
              e.preventDefault()
              void saveTaxSettings()
            }}
          />
          <button className="btn" onClick={() => void saveTaxSettings()} disabled={savingTax}>Сохранить УСН</button>
        </div>
      </section>

      <section className="settings-section-block">
        <div className="settings-section-title">Данные</div>
        <div className="row settings-actions-row">
          <button className="btn" onClick={() => void exportRegistryExcel()} disabled={isExportingRegistry}>Выгрузка базы</button>
          <button className="btn" onClick={() => setIsBackupOpen(true)}>Бэкап</button>
          <button className="btn" onClick={() => void loadAll()}>Обновить статус</button>
        </div>
        {rollingBackup && (
          <div className="settings-inline-note">
            Фоновый backup: {rollingBackup.launch_agent.exists ? "активен" : "не активен"} · {rollingBackup.days} {rollingBackup.time}
            <br />
            current: {rollingBackup.current.exists ? "OK" : "нет"}{rollingBackup.current.updated_at ? ` (${new Date(rollingBackup.current.updated_at).toLocaleString("ru-RU")})` : ""}
            <br />
            prev: {rollingBackup.prev.exists ? "OK" : "нет"}{rollingBackup.prev.updated_at ? ` (${new Date(rollingBackup.prev.updated_at).toLocaleString("ru-RU")})` : ""}
          </div>
        )}
      </section>

      <section className="settings-section-block">
        <div className="settings-section-title">Приложение</div>
        <div className="row settings-actions-row">
          <button className="btn" onClick={() => void openUpdatesPage()} disabled={isUpdatingApp}>
            {isUpdatingApp ? "Запуск..." : "Обновить"}
          </button>
        </div>
      </section>
    </div>
  )

  if (asModal) {
    return (
      <div className="grid settings-modal-compact">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="h1">Настройки</div>
          <button className="btn icon-btn modal-close-btn" aria-label="Закрыть окно" onClick={onClose}>×</button>
        </div>

        <div className="card settings-modal-card">
          {settingsBody}
        </div>

        {msg && (
          <div className="card settings-modal-card">
            <div className="settings-status-ok">{msg}</div>
          </div>
        )}
        {error && (
          <div className="card settings-modal-card">
            <div className="settings-status-error">{error}</div>
          </div>
        )}

        {isBackupOpen && (
          <div className="modal-backdrop" onClick={() => setIsBackupOpen(false)}>
            <div className="panel project-settings-panel project-settings-modal backup-modal" onClick={(e) => e.stopPropagation()}>
              <BackupPage asModal onClose={() => setIsBackupOpen(false)} />
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="grid">
      <div className="card top-panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="h1">Настройки</div>
          <Link className="btn" to="/">← на главную</Link>
        </div>
      </div>

      <div className="card settings-modal-card">
        {settingsBody}
      </div>

      {msg && (
        <div className="card settings-modal-card">
          <div className="settings-status-ok">{msg}</div>
        </div>
      )}
      {error && (
        <div className="card settings-modal-card">
          <div className="settings-status-error">{error}</div>
        </div>
      )}

      {isBackupOpen && (
        <div className="modal-backdrop" onClick={() => setIsBackupOpen(false)}>
          <div className="panel project-settings-panel project-settings-modal backup-modal" onClick={(e) => e.stopPropagation()}>
            <BackupPage asModal onClose={() => setIsBackupOpen(false)} />
          </div>
        </div>
      )}
    </div>
  )
}
