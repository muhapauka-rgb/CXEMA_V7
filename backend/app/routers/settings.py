from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import engine
from ..db import get_db
from ..models import AppSettings, UsnMode, BackupFrequency
from ..schemas import AppSettingsOut, AppSettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _ensure_sqlite_columns() -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(app_settings)"))}
        if "backup_frequency" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE app_settings "
                    "ADD COLUMN backup_frequency VARCHAR(16) NOT NULL DEFAULT 'WEEKLY'"
                )
            )
        if "last_backup_at" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE app_settings "
                    "ADD COLUMN last_backup_at DATETIME NULL"
                )
            )


_ensure_sqlite_columns()


def _get_or_create_settings(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if row:
        if getattr(row, "backup_frequency", None) is None:
            row.backup_frequency = BackupFrequency.WEEKLY
            db.commit()
            db.refresh(row)
        return row
    row = AppSettings(
        id=1,
        usn_mode=UsnMode.OPERATIONAL,
        usn_rate_percent=6.0,
        backup_frequency=BackupFrequency.WEEKLY,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=AppSettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return _get_or_create_settings(db)


@router.patch("", response_model=AppSettingsOut)
def update_settings(payload: AppSettingsUpdate, db: Session = Depends(get_db)):
    row = _get_or_create_settings(db)
    data = payload.model_dump(exclude_unset=True)

    if "usn_mode" in data and data["usn_mode"] is not None:
        mode_raw = str(data["usn_mode"]).strip().upper()
        try:
            row.usn_mode = UsnMode(mode_raw)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="USN_MODE_INVALID") from exc

    if "usn_rate_percent" in data and data["usn_rate_percent"] is not None:
        row.usn_rate_percent = float(data["usn_rate_percent"])

    if "backup_frequency" in data and data["backup_frequency"] is not None:
        freq_raw = str(data["backup_frequency"]).strip().upper()
        try:
            row.backup_frequency = BackupFrequency(freq_raw)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="BACKUP_FREQUENCY_INVALID") from exc

    db.commit()
    db.refresh(row)
    return row
