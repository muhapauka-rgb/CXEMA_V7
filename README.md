# CXEMA V7

Локальная веб‑система смет/учёта ивент‑проектов + подготовка к синхронизации с Google Sheets.

Порты по умолчанию:
- Backend: http://localhost:28011 (или ближайший свободный выше 28011 через `./start_backend.sh`)
- Frontend: http://localhost:13011

## Быстрый старт (Mac)

### 1) Backend (FastAPI)
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 28011
```

### 2) Frontend (React)
```bash
cd frontend
npm i
npm run dev -- --host 0.0.0.0 --port 13011
```

## Google Sheets (текущий этап)
- Сейчас включен `mock`-режим (`CXEMA_SHEETS_MODE=mock`).
- Publish пишет файл в `data/mock_sheets/project_<id>.json`.
- Для проверки Import:
  1) нажми `Publish` в карточке Google Sheets на странице проекта;
  2) отредактируй `estimate_rows` и/или `payments_plan_rows` в mock JSON;
  3) нажми `Import Preview` (генерируется `preview_token`);
  4) нажми `Import Apply` для подтверждённого применения этого preview.

## Google Sheets (real mode)
1) Включи в `backend/.env`:
   - `CXEMA_SHEETS_MODE=real`
   - `CXEMA_GOOGLE_CLIENT_SECRET_FILE=../data/google/client_secret.json`
   - `CXEMA_GOOGLE_TOKEN_FILE=../data/google/token.json`
   - `CXEMA_GOOGLE_OAUTH_REDIRECT_URI=http://localhost:28011/api/google/auth/callback`
2) Положи OAuth client secret JSON в `data/google/client_secret.json`.
3) Перезапусти backend.
4) На странице проекта в блоке `Google Sheets` нажми `Connect Google`, заверши OAuth, затем `Refresh Auth`.
5) После статуса `OAuth connected: yes` доступны `Publish / Import Preview / Import Apply` уже с реальным Google Sheet.
6) OAuth `state` проверяется на сервере и одноразовый (TTL 10 минут), поэтому callback нельзя переиспользовать.

## GitHub (если хочешь залить репозиторий)
1) Создай новый репозиторий на GitHub (например `CXEMA_V7`).
2) В терминале в папке проекта:
```bash
git init
git add .
git commit -m "CXEMA V7: initial skeleton (backend 28011, frontend 13011)"
git branch -M main
git remote add origin <PASTE_YOUR_GITHUB_REPO_URL_HERE>
git push -u origin main
```

> Если Git ругается на имя/почту:
```bash
git config --global user.name "YOUR NAME"
git config --global user.email "you@example.com"
```
