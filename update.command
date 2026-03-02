#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
DESKTOP_DIR="$ROOT_DIR/desktop"
APP_SUPPORT_DIR="$HOME/Library/Application Support/cxema-v7-desktop"
APP_DATA_DIR="$APP_SUPPORT_DIR/data"
LAUNCH_AGENT_LABEL="com.cxema.v7.backup"
LAUNCH_AGENT_FILE="$HOME/Library/LaunchAgents/$LAUNCH_AGENT_LABEL.plist"

log() {
  echo "[$(date +%H:%M:%S)] $*"
}

main() {
  log "Обновление CXEMA V7..."
  cd "$ROOT_DIR"

  if ! command -v git >/dev/null 2>&1; then
    echo "Git не найден. Установи Xcode Command Line Tools и повтори."
    exit 1
  fi

  BRANCH="$(git branch --show-current || true)"
  if [ -z "$BRANCH" ]; then
    echo "Не удалось определить текущую ветку."
    exit 1
  fi

  git fetch --all --prune
  git pull --ff-only origin "$BRANCH"

  log "Обновляю backend зависимости..."
  "$BACKEND_DIR/.venv/bin/pip" install -r "$BACKEND_DIR/requirements.txt"
  "$BACKEND_DIR/.venv/bin/playwright" install chromium

  log "Создаю защитный backup перед запуском обновленной версии..."
  CXEMA_DB_PATH="$APP_DATA_DIR/app.db" "$BACKEND_DIR/.venv/bin/python" -m app.backup_job || true

  log "Обновляю frontend зависимости..."
  (cd "$FRONTEND_DIR" && npm install)

  log "Обновляю desktop зависимости..."
  (cd "$DESKTOP_DIR" && npm install)

  if [ -f "$LAUNCH_AGENT_FILE" ]; then
    launchctl unload "$LAUNCH_AGENT_FILE" >/dev/null 2>&1 || true
    launchctl load "$LAUNCH_AGENT_FILE" >/dev/null 2>&1 || true
  fi

  log "Обновление завершено. Запускаю приложение..."
  (cd "$DESKTOP_DIR" && npm run dev)
}

main "$@"
