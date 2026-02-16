import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { apiGet } from "../api"

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

const GOOGLE_LOGIN_KEY = "cxema_google_login"

export default function SettingsPage() {
  const [googleLogin, setGoogleLogin] = useState("")
  const [googlePassword, setGooglePassword] = useState("")
  const [status, setStatus] = useState<GoogleAuthStatus | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const savedLogin = localStorage.getItem(GOOGLE_LOGIN_KEY) || ""
    setGoogleLogin(savedLogin)
    void refreshStatus()
  }, [])

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

  function saveLoginOnly() {
    localStorage.setItem(GOOGLE_LOGIN_KEY, googleLogin.trim())
    setGooglePassword("")
    setMsg("Логин сохранён локально в браузере. Пароль не хранится и не используется.")
  }

  return (
    <div className="grid">
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="h1">Настройки</div>
          <Link className="btn" to="/">← на главную</Link>
        </div>
      </div>

      <div className="card">
        <div className="h1">Google</div>

        <div className="grid">
          <input
            className="input"
            placeholder="Google login (email)"
            value={googleLogin}
            onChange={(e) => setGoogleLogin(e.target.value)}
          />
          <input
            className="input"
            type="password"
            placeholder="Google password (не используется)"
            value={googlePassword}
            onChange={(e) => setGooglePassword(e.target.value)}
          />
          <div className="row">
            <button className="btn" onClick={saveLoginOnly}>Сохранить логин</button>
            <button className="btn" onClick={() => void refreshStatus()}>Проверить подключение</button>
            <button className="btn" onClick={() => void startOauth()}>Подключить Google (OAuth)</button>
          </div>
        </div>
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
    </div>
  )
}
