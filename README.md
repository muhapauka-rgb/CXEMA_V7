# CXEMA V7

Локальная веб‑система смет/учёта ивент‑проектов + подготовка к синхронизации с Google Sheets.

Порты по умолчанию:
- Backend: http://localhost:8011
- Frontend: http://localhost:3011

## Быстрый старт (Mac)

### 1) Backend (FastAPI)
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8011
```

### 2) Frontend (React)
```bash
cd frontend
npm i
npm run dev -- --host 0.0.0.0 --port 3011
```

## GitHub (если хочешь залить репозиторий)
1) Создай новый репозиторий на GitHub (например `CXEMA_V7`).
2) В терминале в папке проекта:
```bash
git init
git add .
git commit -m "CXEMA V7: initial skeleton (backend 8011, frontend 3011)"
git branch -M main
git remote add origin <PASTE_YOUR_GITHUB_REPO_URL_HERE>
git push -u origin main
```

> Если Git ругается на имя/почту:
```bash
git config --global user.name "YOUR NAME"
git config --global user.email "you@example.com"
```
