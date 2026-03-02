import { useEffect, useMemo, useState } from "react"
import { apiGet, apiPostForm } from "../api"

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

type Props = {
  onFinish: () => void
}

type ReadinessIssue = {
  title: string
  fix: string
}

function extractFirstUrl(text: string): string | null {
  const m = String(text || "").match(/https?:\/\/[^\s"'<>]+/i)
  return m ? m[0] : null
}

function buildReadinessIssues(status: GoogleAuthStatus | null): ReadinessIssue[] {
  if (!status) {
    return [{ title: "Не удалось получить статус подключения", fix: "Нажми «Проверить подключение». Если не помогает, перезапусти приложение." }]
  }

  const issues: ReadinessIssue[] = []
  const mode = String(status.mode || "").toLowerCase()
  if (mode !== "real") {
    issues.push({
      title: "Google режим выключен (mode != real)",
      fix: "В backend/.env установи CXEMA_SHEETS_MODE=real и перезапусти backend.",
    })
  }
  if (!status.client_secret_configured) {
    issues.push({
      title: "Не настроен Google client_secret",
      fix: "Создай OAuth 2.0 Client ID (Desktop app) в Google Cloud Console, скачай client_secret.json и загрузи его кнопкой «Загрузить client_secret.json».",
    })
  }
  if (!status.connected) {
    issues.push({
      title: "Google OAuth еще не подключен",
      fix: "Нажми «Подключить Google», выбери аккаунт, нажми «Разрешить», затем «Проверить подключение».",
    })
  }

  const lastError = String(status.last_error || "")
  if (lastError.includes("SERVICE_DISABLED") || lastError.includes("sheets.googleapis.com")) {
    const url = extractFirstUrl(lastError)
    issues.push({
      title: "Google Sheets API выключен",
      fix: `Включи Google Sheets API: https://console.cloud.google.com/apis/library/sheets.googleapis.com . Включи Google Drive API: https://console.cloud.google.com/apis/library/drive.googleapis.com . Подожди 1-2 минуты.${url ? ` Ссылка из ошибки: ${url}` : ""}`,
    })
  }
  if (lastError.includes("GOOGLE_TOKEN_INVALID") || lastError.includes("GOOGLE_TOKEN_REFRESH_FAILED")) {
    issues.push({
      title: "Токен Google недействителен",
      fix: "Повтори подключение через «Подключить Google» и заново выдай доступ.",
    })
  }
  if (lastError.includes("GOOGLE_AUTH_REQUIRED")) {
    issues.push({
      title: "Нужна первичная авторизация",
      fix: "Нажми «Подключить Google» и заверши OAuth-шаг до конца.",
    })
  }
  if (lastError.includes("GOOGLE_OAUTH_STATE_INVALID") || lastError.includes("GOOGLE_OAUTH_STATE_EXPIRED")) {
    issues.push({
      title: "Истекла или некорректна OAuth-сессия",
      fix: "Нажми «Подключить Google» заново, полностью пройди окно авторизации и вернись в приложение.",
    })
  }
  if (lastError.includes("access_denied")) {
    issues.push({
      title: "Доступ отклонен в окне Google",
      fix: "Повтори подключение и на экране разрешений нажми «Разрешить».",
    })
  }
  if (lastError.includes("redirect_uri_mismatch")) {
    issues.push({
      title: "Неверный redirect URI в Google OAuth",
      fix: `В Google Cloud OAuth добавь callback: ${status.redirect_uri}`,
    })
  }
  if (lastError.includes("invalid_client")) {
    issues.push({
      title: "Неверный OAuth client_secret",
      fix: "Проверь файл client_secret.json (Client ID/Secret) и перезапусти backend.",
    })
  }
  if (lastError.includes("insufficientPermissions") || lastError.includes("insufficient authentication scopes")) {
    issues.push({
      title: "Недостаточно прав у OAuth-токена",
      fix: "Нажми «Подключить Google» и выдай приложению полный запрошенный доступ.",
    })
  }
  if (lastError && issues.length === 0) {
    issues.push({
      title: "Обнаружена нестандартная ошибка Google",
      fix: `Текст ошибки: ${lastError}`,
    })
  }

  return issues
}

export default function OnboardingWizard({ onFinish }: Props) {
  const [step, setStep] = useState(1)
  const [status, setStatus] = useState<GoogleAuthStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [checking, setChecking] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [uploadingSecret, setUploadingSecret] = useState(false)

  useEffect(() => {
    void refreshStatus()
  }, [])

  const canGoNext = useMemo(() => {
    if (step === 1) return true
    if (step === 2) return !!status?.connected
    return true
  }, [step, status])
  const issues = useMemo(() => buildReadinessIssues(status), [status])

  async function refreshStatus(silent = false) {
    try {
      if (!silent) setErr(null)
      setChecking(true)
      const out = await apiGet<GoogleAuthStatus>("/api/google/auth/status")
      setStatus(out)
    } catch (e) {
      if (!silent) setErr(String(e))
    } finally {
      setChecking(false)
    }
  }

  async function startOauth() {
    try {
      setErr(null)
      setBusy(true)
      const out = await apiGet<GoogleAuthStart>("/api/google/auth/start")
      window.open(out.auth_url, "_blank", "noopener,noreferrer")
      setMsg("Открыто окно Google. Разреши доступ и вернись сюда, затем нажми «Проверить подключение».")
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function uploadClientSecret(file: File) {
    try {
      setErr(null)
      setUploadingSecret(true)
      const form = new FormData()
      form.append("file", file)
      await apiPostForm("/api/google/auth/client-secret", form)
      setMsg("Файл client_secret.json загружен. Теперь нажми «Проверить подключение».")
      await refreshStatus(true)
    } catch (e) {
      const text = String(e || "")
      if (text.includes("GOOGLE_CLIENT_SECRET_INVALID_JSON")) {
        setErr("Файл не JSON. Скачай корректный client_secret.json из Google Cloud Console и загрузи его снова.")
      } else if (text.includes("GOOGLE_CLIENT_SECRET_INVALID_FORMAT")) {
        setErr("Некорректный формат client_secret.json. Нужен OAuth 2.0 Client ID (Desktop app).")
      } else {
        setErr(text)
      }
    } finally {
      setUploadingSecret(false)
    }
  }

  useEffect(() => {
    if (step !== 2) return
    if (status?.connected) return
    const timer = window.setInterval(() => {
      void refreshStatus(true)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [step, status?.connected])

  function next() {
    if (!canGoNext) return
    setStep((s) => Math.min(3, s + 1))
  }

  function back() {
    setStep((s) => Math.max(1, s - 1))
  }

  return (
    <div className="modal-backdrop onboarding-backdrop">
      <div className="panel onboarding-panel" onClick={(e) => e.stopPropagation()}>
        <div className="h1">Установка CXEMA V7</div>
        <div className="muted">Шаг {step} из 3</div>

        {step === 1 && (
          <div className="grid onboarding-content">
            <div className="onboarding-title">Добро пожаловать</div>
            <div className="muted">
              Сейчас настроим приложение для работы.
            </div>
            <div className="onboarding-list">
              <div>1. На следующем шаге откроется Google-окно авторизации.</div>
              <div>2. Нужно выбрать Google-аккаунт и нажать «Разрешить».</div>
              <div>3. Пока подключение не подтверждено, установка не завершится.</div>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="grid onboarding-content">
            <div className="onboarding-title">Подключение Google OAuth</div>
            <div className="onboarding-list">
              <div>1. Открой Google Cloud Console: APIs & Services.</div>
              <div>2. Включи Google Sheets API и Google Drive API.</div>
              <div>3. Создай OAuth 2.0 Client ID (тип: Desktop app).</div>
              <div>4. Скачай файл client_secret.json и загрузи его ниже.</div>
              <div>5. Нажми «Подключить Google», выбери аккаунт, нажми «Разрешить».</div>
              <div>6. Вернись сюда и нажми «Проверить подключение».</div>
            </div>

            <div className="row settings-actions-row">
              <label className="btn" style={{ cursor: uploadingSecret ? "not-allowed" : "pointer", opacity: uploadingSecret ? 0.55 : 1 }}>
                Загрузить client_secret.json
                <input
                  type="file"
                  accept=".json,application/json"
                  style={{ display: "none" }}
                  disabled={uploadingSecret || busy}
                  onChange={(e) => {
                    const f = e.currentTarget.files?.[0]
                    if (f) void uploadClientSecret(f)
                    e.currentTarget.value = ""
                  }}
                />
              </label>
              <button className="btn" onClick={() => void startOauth()} disabled={busy}>
                Подключить Google
              </button>
              <button className="btn" onClick={() => void refreshStatus()} disabled={busy || checking || uploadingSecret}>
                Проверить подключение
              </button>
            </div>

            <div className={`settings-inline-note ${status?.connected ? "settings-status-ok" : "settings-status-error"}`}>
              Статус готовности: {status?.connected ? "ГОТОВО" : "НЕ ГОТОВО"} {checking ? "· проверка..." : ""}
            </div>

            {!status?.connected && (
              <div className="onboarding-list">
                {issues.map((issue, idx) => (
                  <div key={`${issue.title}-${idx}`}>
                    • <strong>{issue.title}.</strong> {issue.fix}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {step === 3 && (
          <div className="grid onboarding-content">
            <div className="onboarding-title">Готово</div>
            <div className="muted">Установка завершена, Google подключен. Можно работать.</div>
          </div>
        )}

        {msg && <div className="settings-status-ok">{msg}</div>}
        {err && <div className="settings-status-error">{err}</div>}

        <div className="row onboarding-actions">
          <button className="btn" onClick={back} disabled={step === 1 || busy}>Назад</button>
          {step < 3 ? (
            <button className="btn tab-active" onClick={next} disabled={!canGoNext || busy}>
              Далее
            </button>
          ) : (
            <button className="btn tab-active" onClick={onFinish}>
              Завершить
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
