#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONT_DIR="$ROOT_DIR/frontend"
PORT_FILE="$ROOT_DIR/.run/backend_port.txt"

if [ ! -f "$PORT_FILE" ]; then
  echo "❌ Не найден файл порта backend: $PORT_FILE"
  echo "Сначала запусти backend: ./start_backend.sh"
  exit 1
fi

BACKEND_PORT="$(cat "$PORT_FILE" | tr -d '[:space:]')"
if [ -z "$BACKEND_PORT" ]; then
  echo "❌ Порт backend пустой в файле: $PORT_FILE"
  echo "Перезапусти backend: ./start_backend.sh"
  exit 1
fi

cd "$FRONT_DIR"

echo "✅ Frontend will use backend: http://localhost:$BACKEND_PORT"
echo "✅ Frontend will run on:     http://localhost:13011"
echo ""

VITE_API_BASE="http://localhost:$BACKEND_PORT" exec npm run dev -- --host 0.0.0.0 --port 13011
