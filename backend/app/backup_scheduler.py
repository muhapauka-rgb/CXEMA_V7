from __future__ import annotations

import asyncio
import calendar
import logging
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from .db import SessionLocal
from .settings import settings
from .models import AppSettings, BackupFrequency, UsnMode
from .routers.backup import save_backup_to_disk, prune_backups_older_than_months
from sqlalchemy.orm import Session

logger = logging.getLogger("cxema.backup")

_POLL_SECONDS = 60
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


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (Path(__file__).resolve().parents[1] / path).resolve()


def _parse_days(raw: str) -> set[int]:
    mapping = {
        "MON": 0,
        "TUE": 1,
        "WED": 2,
        "THU": 3,
        "FRI": 4,
        "SAT": 5,
        "SUN": 6,
    }
    out: set[int] = set()
    for token in str(raw or "").upper().replace(" ", "").split(","):
        if token in mapping:
            out.add(mapping[token])
    return out or {0, 2, 4}


def _parse_hm(raw: str) -> tuple[int, int]:
    text = str(raw or "23:00").strip()
    try:
        hour_s, min_s = text.split(":", 1)
        hour = max(0, min(23, int(hour_s)))
        minute = max(0, min(59, int(min_s)))
        return hour, minute
    except Exception:
        return 23, 0


def _is_due_mwf(now: datetime, last_backup_at: Optional[datetime]) -> bool:
    allowed_days = _parse_days(settings.AUTO_BACKUP_DAYS)
    hour, minute = _parse_hm(settings.AUTO_BACKUP_TIME)
    if now.weekday() not in allowed_days:
        return False
    if (now.hour, now.minute) < (hour, minute):
        return False
    if last_backup_at is None:
        return True
    return last_backup_at.date() < now.date()


def _rolling_db_backup() -> Path:
    db_path = _resolve_path(settings.DB_PATH)
    if not db_path.exists():
        raise RuntimeError(f"DB_NOT_FOUND: {db_path}")

    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    current_path = backup_dir / settings.AUTO_BACKUP_CURRENT_FILE
    prev_path = backup_dir / settings.AUTO_BACKUP_PREV_FILE

    temp_path = backup_dir / f".tmp-{os.getpid()}-{int(datetime.utcnow().timestamp())}.db"
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(temp_path))
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()

    if current_path.exists():
        os.replace(str(current_path), str(prev_path))
    os.replace(str(temp_path), str(current_path))
    return current_path


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
    now = datetime.now()
    with SessionLocal() as db:
        row = _get_or_create_settings(db)
        if str(settings.AUTO_BACKUP_MODE).strip().upper() == "MWF_ROLLING_DB":
            if not _is_due_mwf(now, row.last_backup_at):
                return
            target = _rolling_db_backup()
        else:
            prune_backups_older_than_months(4)
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
