import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { apiGet, apiPatch } from "../api"
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

const GOOGLE_LOGIN_KEY = "cxema_google_login"
const GOOGLE_PASSWORD_KEY = "cxema_google_password"

type SettingsPageProps = {
  asModal?: boolean
  onClose?: () => void
}

export default function SettingsPage({ asModal = false, onClose }: SettingsPageProps) {
  const [googleLogin, setGoogleLogin] = useState("")
  const [googlePassword, setGooglePassword] = useState("")
  const [status, setStatus] = useState<GoogleAuthStatus | null>(null)
  const [usnMode, setUsnMode] = useState<"LEGAL" | "OPERATIONAL">("OPERATIONAL")
  const [usnRateRaw, setUsnRateRaw] = useState("6")
  const [savingTax, setSavingTax] = useState(false)
  const [isBackupOpen, setIsBackupOpen] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const savedLogin = localStorage.getItem(GOOGLE_LOGIN_KEY) || ""
    const savedPassword = localStorage.getItem(GOOGLE_PASSWORD_KEY) || ""
    setGoogleLogin(savedLogin)
    setGooglePassword(savedPassword)
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

  function saveGoogleCredentials() {
    localStorage.setItem(GOOGLE_LOGIN_KEY, googleLogin.trim())
    localStorage.setItem(GOOGLE_PASSWORD_KEY, googlePassword)
    setMsg("Логин и пароль сохранены локально в браузере.")
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

  const settingsBody = (
    <>
      <div className="h1">Google и налоги</div>

      <div className="grid">
        <div className="muted" style={{ fontWeight: 700, color: "var(--text)" }}>Google</div>
        <input
          className="input"
          placeholder="Google login (email)"
          value={googleLogin}
          onChange={(e) => setGoogleLogin(e.target.value)}
        />
        <input
          className="input"
          type="password"
          placeholder="Google password"
          value={googlePassword}
          onChange={(e) => setGooglePassword(e.target.value)}
        />
        <div className="row">
          <button className="btn" onClick={saveGoogleCredentials}>Сохранить логин и пароль</button>
          <button className="btn" onClick={() => void refreshStatus()}>Проверить подключение</button>
          <button className="btn" onClick={() => void startOauth()}>Подключить Google (OAuth)</button>
        </div>

        <div className="muted" style={{ marginTop: 8, fontWeight: 700, color: "var(--text)" }}>УСН</div>
        <div className="row">
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
        <div className="row">
          <button className="btn" onClick={() => void saveTaxSettings()} disabled={savingTax}>Сохранить УСН</button>
        </div>

        <div className="row" style={{ marginTop: 6 }}>
          <button className="btn" onClick={() => setIsBackupOpen(true)}>Бэкап</button>
        </div>
      </div>
    </>
  )

  if (asModal) {
    return (
      <div className="grid">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="h1">Настройки</div>
          <button className="btn icon-btn modal-close-btn" aria-label="Закрыть окно" onClick={onClose}>×</button>
        </div>

        <div className="card">
          {settingsBody}
        </div>

        <div className="card">
          <div className="h1">Статус интеграции</div>
          <div className="muted">mode: {status?.mode || "—"}</div>
          <div className="muted">connected: {status?.connected ? "yes" : "no"}</div>
          <div className="muted">client_secret_configured: {status?.client_secret_configured ? "yes" : "no"}</div>
          <div className="muted">redirect_uri: {status?.redirect_uri || "—"}</div>
          <div className="muted">token_file_path: {status?.token_file_path || "—"}</div>
          {status?.last_error && <div className="muted" style={{ color: "#ff9a9a" }}>{status.last_error}</div>}
        </div>

        {msg && (
          <div className="card">
            <div className="muted" style={{ color: "#7fffb6" }}>{msg}</div>
          </div>
        )}
        {error && (
          <div className="card">
            <div className="muted" style={{ color: "#ff9a9a" }}>{error}</div>
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

      <div className="card">
        {settingsBody}
      </div>

      <div className="card">
        <div className="h1">Статус интеграции</div>
        <div className="muted">mode: {status?.mode || "—"}</div>
        <div className="muted">connected: {status?.connected ? "yes" : "no"}</div>
        <div className="muted">client_secret_configured: {status?.client_secret_configured ? "yes" : "no"}</div>
        <div className="muted">redirect_uri: {status?.redirect_uri || "—"}</div>
        <div className="muted">token_file_path: {status?.token_file_path || "—"}</div>
        {status?.last_error && <div className="muted" style={{ color: "#ff9a9a" }}>{status.last_error}</div>}
      </div>

      {msg && (
        <div className="card">
          <div className="muted" style={{ color: "#7fffb6" }}>{msg}</div>
        </div>
      )}
      {error && (
        <div className="card">
          <div className="muted" style={{ color: "#ff9a9a" }}>{error}</div>
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
