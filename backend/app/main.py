from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .settings import settings
from .routers import health, projects, overview, sheets, google_auth, life, discounts, settings as settings_router, backup, exports
from .backup_scheduler import start_auto_backup_scheduler, stop_auto_backup_scheduler

app = FastAPI(title="CXEMA V7 API", version="0.1.0")

origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(projects.router)
app.include_router(overview.router)
app.include_router(sheets.router)
app.include_router(google_auth.router)
app.include_router(life.router)
app.include_router(discounts.router)
app.include_router(settings_router.router)
app.include_router(backup.router)
app.include_router(exports.router)


@app.on_event("startup")
async def _on_startup() -> None:
    start_auto_backup_scheduler()


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    await stop_auto_backup_scheduler()
