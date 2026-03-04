const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron")
const path = require("path")
const fs = require("fs")
const { spawn } = require("child_process")
const http = require("http")

const ROOT = path.resolve(__dirname, "..")
const RESOURCES_ROOT = app.isPackaged ? process.resourcesPath : ROOT
const FRONTEND_URL = process.env.CXEMA_FRONTEND_URL || "http://localhost:13011"
const BACKEND_HEALTH_URL = process.env.CXEMA_BACKEND_HEALTH_URL || "http://localhost:28011/health"
const STARTUP_TIMEOUT_MS = 45_000
const POLL_MS = 700

let mainWindow = null
let backendProc = null
let frontendProc = null

function updateCommandPath() {
  return path.join(ROOT, "update.command")
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true })
}

function desktopEnv() {
  app.setName("CXEMA V7")
  const userData = app.getPath("userData")
  const dataDir = path.join(userData, "data")
  const googleDir = path.join(userData, "google")
  const mockSheetsDir = path.join(userData, "mock_sheets")
  ensureDir(dataDir)
  ensureDir(googleDir)
  ensureDir(mockSheetsDir)

  const env = { ...process.env }
  env.CXEMA_DB_PATH = path.join(dataDir, "app.db")
  env.CXEMA_SHEETS_MODE = "real"
  env.CXEMA_SHEETS_MOCK_DIR = mockSheetsDir
  env.CXEMA_GOOGLE_TOKEN_FILE = path.join(googleDir, "token.json")
  env.CXEMA_GOOGLE_CLIENT_SECRET_FILE =
    process.env.CXEMA_GOOGLE_CLIENT_SECRET_FILE || path.join(googleDir, "client_secret.json")
  env.CXEMA_GOOGLE_OAUTH_REDIRECT_URI = "http://localhost:28011/api/google/auth/callback"
  env.CXEMA_AUTO_BACKUP_MODE = "MWF_ROLLING_DB"
  env.CXEMA_AUTO_BACKUP_DAYS = "MON,WED,FRI"
  env.CXEMA_AUTO_BACKUP_TIME = "23:00"
  env.CXEMA_AUTO_BACKUP_CURRENT_FILE = "app.backup.current.db"
  env.CXEMA_AUTO_BACKUP_PREV_FILE = "app.backup.prev.db"
  return env
}

function isUp(url) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: 2000 }, (res) => {
      res.resume()
      resolve(res.statusCode && res.statusCode >= 200 && res.statusCode < 500)
    })
    req.on("error", () => resolve(false))
    req.on("timeout", () => {
      req.destroy()
      resolve(false)
    })
  })
}

async function waitUntil(url, timeoutMs) {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    // eslint-disable-next-line no-await-in-loop
    const ok = await isUp(url)
    if (ok) return true
    // eslint-disable-next-line no-await-in-loop
    await new Promise((r) => setTimeout(r, POLL_MS))
  }
  return false
}

function spawnBackend() {
  const cwd = path.join(RESOURCES_ROOT, "backend")
  const pyBin = path.join(cwd, ".venv", "bin", "python")
  if (!fs.existsSync(pyBin)) {
    throw new Error(`BACKEND_PYTHON_NOT_FOUND: ${pyBin}`)
  }
  const env = desktopEnv()
  backendProc = spawn(
    pyBin,
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "28011"],
    {
      cwd,
      stdio: "ignore",
      detached: false,
      env,
    },
  )
}

function spawnFrontend() {
  const cwd = path.join(ROOT, "frontend")
  const env = desktopEnv()
  frontendProc = spawn("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", "13011"], {
    cwd,
    stdio: "ignore",
    detached: false,
    env,
  })
}

function stopChild(child) {
  if (!child || child.killed) return
  try {
    child.kill("SIGTERM")
  } catch {
    // ignore
  }
}

async function ensureServices() {
  const backendAlive = await isUp(BACKEND_HEALTH_URL)
  if (!backendAlive) {
    spawnBackend()
    const ok = await waitUntil(BACKEND_HEALTH_URL, STARTUP_TIMEOUT_MS)
    if (!ok) throw new Error("Backend не запустился")
  }

  if (app.isPackaged) return

  const frontendAlive = await isUp(FRONTEND_URL)
  if (!frontendAlive) {
    spawnFrontend()
    const ok = await waitUntil(FRONTEND_URL, STARTUP_TIMEOUT_MS)
    if (!ok) throw new Error("Frontend не запустился")
  }
}

async function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    title: "CXEMA V7",
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
      preload: path.join(__dirname, "preload.cjs"),
    },
  })
  if (app.isPackaged) {
    const entry = path.join(RESOURCES_ROOT, "frontend-dist", "index.html")
    if (!fs.existsSync(entry)) {
      throw new Error(`FRONTEND_DIST_NOT_FOUND: ${entry}`)
    }
    await mainWindow.loadFile(entry)
    return
  }
  await mainWindow.loadURL(FRONTEND_URL)
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit()
})

app.on("before-quit", () => {
  stopChild(frontendProc)
  stopChild(backendProc)
})

app.whenReady().then(async () => {
  try {
    ipcMain.handle("cxema:update-command", async () => {
      const script = updateCommandPath()
      if (!fs.existsSync(script)) {
        throw new Error(`UPDATE_SCRIPT_NOT_FOUND: ${script}`)
      }
      await shell.openPath(script)
      return { ok: true }
    })

    await ensureServices()
    await createMainWindow()
  } catch (err) {
    dialog.showErrorBox("Ошибка запуска CXEMA V7", String(err))
    app.quit()
  }
})
