from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import (
    SheetsImportApplyIn,
    SheetsImportApplyOut,
    SheetsImportPreviewOut,
    SheetsPublishOut,
    SheetsStatusOut,
)
from ..sheets_service import (
    apply_import_from_sheets,
    get_sheets_status,
    preview_import_from_sheets,
    publish_to_sheets,
)

router = APIRouter(prefix="/api/projects", tags=["sheets"])


def _handle_service_error(exc: Exception) -> None:
    message = str(exc)
    if message == "PROJECT_NOT_FOUND":
        raise HTTPException(404, message) from exc
    if message in {"PREVIEW_CONFIRM_REQUIRED", "PREVIEW_TOKEN_EXPIRED"}:
        raise HTTPException(409, message) from exc
    if message == "GOOGLE_AUTH_REQUIRED":
        raise HTTPException(401, message) from exc
    if message == "SHEET_NOT_PUBLISHED":
        raise HTTPException(409, message) from exc
    if message in {"GOOGLE_LIBRARIES_NOT_INSTALLED", "GOOGLE_CLIENT_SECRET_FILE_NOT_FOUND"}:
        raise HTTPException(500, message) from exc
    if message == "SHEET_FORMAT_INVALID":
        raise HTTPException(422, message) from exc
    if message == "GOOGLE_SHEETS_REAL_NOT_IMPLEMENTED":
        raise HTTPException(501, message) from exc
    raise HTTPException(400, message) from exc


@router.get("/{project_id}/sheets/status", response_model=SheetsStatusOut)
def status(project_id: int, db: Session = Depends(get_db)):
    try:
        return get_sheets_status(db, project_id)
    except Exception as exc:  # pragma: no cover
        _handle_service_error(exc)


@router.post("/{project_id}/sheets/publish", response_model=SheetsPublishOut)
def publish(project_id: int, db: Session = Depends(get_db)):
    try:
        return publish_to_sheets(db, project_id)
    except Exception as exc:  # pragma: no cover
        _handle_service_error(exc)


@router.post("/{project_id}/sheets/import/preview", response_model=SheetsImportPreviewOut)
def import_preview(project_id: int, db: Session = Depends(get_db)):
    try:
        return preview_import_from_sheets(db, project_id)
    except Exception as exc:  # pragma: no cover
        _handle_service_error(exc)


@router.post("/{project_id}/sheets/import/apply", response_model=SheetsImportApplyOut)
def import_apply(project_id: int, payload: SheetsImportApplyIn, db: Session = Depends(get_db)):
    try:
        return apply_import_from_sheets(db, project_id, payload.preview_token)
    except Exception as exc:  # pragma: no cover
        _handle_service_error(exc)
