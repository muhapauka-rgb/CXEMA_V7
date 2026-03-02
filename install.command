#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
DESKTOP_DIR="$ROOT_DIR/desktop"
APP_SUPPORT_DIR="$HOME/Library/Application Support/cxema-v7-desktop"
APP_DATA_DIR="$APP_SUPPORT_DIR/data"
APP_GOOGLE_DIR="$APP_SUPPORT_DIR/google"
LAUNCH_AGENT_LABEL="com.cxema.v7.backup"
LAUNCH_AGENT_FILE="$HOME/Library/LaunchAgents/$LAUNCH_AGENT_LABEL.plist"

log() {
  echo "[$(date +%H:%M:%S)] $*"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

install_homebrew_if_needed() {
  if need_cmd brew; then
    return
  fi
  log "Homebrew не найден. Устанавливаю..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  fi
}

install_base_tools() {
  install_homebrew_if_needed

  if ! need_cmd python3; then
    log "Устанавливаю Python3..."
    brew install python
  fi

  if ! need_cmd node; then
    log "Устанавливаю Node.js..."
    brew install node
  fi

  if ! need_cmd npm; then
    log "Устанавливаю npm..."
    brew install npm
  fi
}

setup_backend() {
  log "Настройка backend..."
  cd "$BACKEND_DIR"

  if [ ! -d ".venv" ]; then
    python3 -m venv .venv
  fi

  .venv/bin/pip install --upgrade pip setuptools wheel
  .venv/bin/pip install -r requirements.txt

  if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
  fi

  # Нужно для PDF-рендера в смете.
  .venv/bin/playwright install chromium
}

setup_frontend() {
  log "Настройка frontend..."
  cd "$FRONTEND_DIR"
  npm install
}

setup_desktop() {
  log "Настройка desktop-оболочки..."
  cd "$DESKTOP_DIR"
  npm install
}

install_backup_launch_agent() {
  log "Настройка фонового backup (ПН/СР/ПТ 23:00)..."
  mkdir -p "$APP_DATA_DIR" "$APP_GOOGLE_DIR" "$HOME/Library/LaunchAgents"

  cat > "$LAUNCH_AGENT_FILE" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LAUNCH_AGENT_LABEL</string>
  <key>WorkingDirectory</key>
  <string>$BACKEND_DIR</string>
  <key>ProgramArguments</key>
  <array>
    <string>$BACKEND_DIR/.venv/bin/python</string>
    <string>-m</string>
    <string>app.backup_job</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CXEMA_DB_PATH</key>
    <string>$APP_DATA_DIR/app.db</string>
    <key>CXEMA_AUTO_BACKUP_MODE</key>
    <string>MWF_ROLLING_DB</string>
    <key>CXEMA_AUTO_BACKUP_DAYS</key>
    <string>MON,WED,FRI</string>
    <key>CXEMA_AUTO_BACKUP_TIME</key>
    <string>23:00</string>
  </dict>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>23</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>23</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>6</integer><key>Hour</key><integer>23</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>RunAtLoad</key>
  <false/>
  <key>StandardOutPath</key>
  <string>$APP_SUPPORT_DIR/backup.log</string>
  <key>StandardErrorPath</key>
  <string>$APP_SUPPORT_DIR/backup.err.log</string>
</dict>
</plist>
EOF

  launchctl unload "$LAUNCH_AGENT_FILE" >/dev/null 2>&1 || true
  launchctl load "$LAUNCH_AGENT_FILE"
  log "Фоновый backup зарегистрирован: $LAUNCH_AGENT_LABEL"
}

launch_desktop() {
  log "Запускаю приложение CXEMA V7..."
  cd "$DESKTOP_DIR"
  log "В приложении откроется мастер установки."
  log "Обязательный шаг: Google OAuth (выбор аккаунта + Разрешить), без этого мастер не завершится."
  npm run dev
}

main() {
  log "Старт установки CXEMA V7"
  install_base_tools
  setup_backend
  setup_frontend
  setup_desktop
  install_backup_launch_agent
  log "Установка завершена."
  launch_desktop
}

main "$@"
