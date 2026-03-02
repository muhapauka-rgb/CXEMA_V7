#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
RUN_DIR="$ROOT_DIR/.run"
PORT_FILE="$RUN_DIR/backend_port.txt"

mkdir -p "$RUN_DIR"

cd "$BACKEND_DIR"
source .venv/bin/activate

PORT=28011
while lsof -i :"$PORT" >/dev/null 2>&1; do
  PORT=$((PORT+1))
done

echo "$PORT" > "$PORT_FILE"

echo "✅ Backend will run on: http://127.0.0.1:$PORT"
echo "   Saved port to: $PORT_FILE"
echo "   Health: http://127.0.0.1:$PORT/health"
echo ""

exec uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
