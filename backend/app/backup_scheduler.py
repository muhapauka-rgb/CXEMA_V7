from __future__ import annotations

import asyncio
import calendar
import logging
from datetime import datetime, timedelta
from typing import Optional

from .db import SessionLocal
from .models import AppSettings, BackupFrequency, UsnMode
from .routers.backup import save_backup_to_disk, prune_backups_older_than_months
from sqlalchemy.orm import Session

logger = logging.getLogger("cxema.backup")

_POLL_SECONDS = 300
_scheduler_task: Optional[asyncio.Task] = None
_scheduler_stop: Optional[asyncio.Event] = None


def _normalize_frequency(raw: object) -> str:
    if isinstance(raw, BackupFrequency):
        return raw.value
    text = str(raw or "WEEKLY").strip().upper()
    if text not in {"OFF", "DAILY", "WEEKLY", "MONTHLY"}:
        return "WEEKLY"
    return text


def _add_month(dt: datetime) -> datetime:
    month = dt.month + 1
    year = dt.year
    if month > 12:
        month = 1
        year += 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _is_due(now: datetime, last_backup_at: Optional[datetime], frequency: str) -> bool:
    if frequency == "OFF":
        return False
    if last_backup_at is None:
        return True
    if frequency == "DAILY":
        return now >= last_backup_at + timedelta(days=1)
    if frequency == "WEEKLY":
        return now >= last_backup_at + timedelta(days=7)
    if frequency == "MONTHLY":
        return now >= _add_month(last_backup_at)
    return now >= last_backup_at + timedelta(days=7)


def _get_or_create_settings(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if row:
        return row
    row = AppSettings(
        id=1,
        usn_mode=UsnMode.OPERATIONAL,
        usn_rate_percent=6.0,
        backup_frequency=BackupFrequency.WEEKLY,
        last_backup_at=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def run_backup_cycle() -> None:
    now = datetime.utcnow()
    with SessionLocal() as db:
        prune_backups_older_than_months(4)
        row = _get_or_create_settings(db)
        frequency = _normalize_frequency(getattr(row, "backup_frequency", BackupFrequency.WEEKLY))
        if not _is_due(now, row.last_backup_at, frequency):
            return
        target = save_backup_to_disk(db)
        row.last_backup_at = now
        db.commit()
        logger.info("Auto backup created: %s", target)


async def _scheduler_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            run_backup_cycle()
        except Exception:
            logger.exception("Auto backup cycle failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_POLL_SECONDS)
        except asyncio.TimeoutError:
            continue


def start_auto_backup_scheduler() -> None:
    global _scheduler_task, _scheduler_stop
    if _scheduler_task and not _scheduler_task.done():
        return
    _scheduler_stop = asyncio.Event()
    _scheduler_task = asyncio.create_task(_scheduler_loop(_scheduler_stop))
    logger.info("Auto backup scheduler started")


async def stop_auto_backup_scheduler() -> None:
    global _scheduler_task, _scheduler_stop
    if _scheduler_stop:
        _scheduler_stop.set()
    if _scheduler_task:
        try:
            await _scheduler_task
        except Exception:
            logger.exception("Auto backup scheduler stop failed")
    _scheduler_task = None
    _scheduler_stop = None
