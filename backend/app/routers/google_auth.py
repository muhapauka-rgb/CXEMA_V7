from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from ..schemas import GoogleAuthStartOut, GoogleAuthStatusOut
from ..sheets_service import complete_google_oauth, get_google_auth_status, start_google_oauth

router = APIRouter(prefix="/api/google", tags=["google-auth"])


def _handle_error(exc: Exception) -> None:
    message = str(exc)
    if message == "GOOGLE_AUTH_REAL_MODE_REQUIRED":
        raise HTTPException(409, message) from exc
    if message == "GOOGLE_CLIENT_SECRET_FILE_NOT_FOUND":
        raise HTTPException(404, message) from exc
    if message in {"GOOGLE_OAUTH_STATE_INVALID", "GOOGLE_OAUTH_STATE_EXPIRED"}:
        raise HTTPException(409, message) from exc
    if message in {"GOOGLE_LIBRARIES_NOT_INSTALLED", "GOOGLE_TOKEN_INVALID"}:
        raise HTTPException(500, message) from exc
    raise HTTPException(400, message) from exc


@router.get("/auth/status", response_model=GoogleAuthStatusOut)
def auth_status():
    try:
        return get_google_auth_status()
    except Exception as exc:  # pragma: no cover
        _handle_error(exc)


@router.get("/auth/start", response_model=GoogleAuthStartOut)
def auth_start():
    try:
        return start_google_oauth()
    except Exception as exc:  # pragma: no cover
        _handle_error(exc)


@router.get("/auth/callback", response_class=HTMLResponse)
def auth_callback(
    state: str = Query(...),
    code: str = Query(...),
):
    try:
        complete_google_oauth(state=state, code=code)
        return HTMLResponse(
            content=(
                "<html><body style='font-family:sans-serif;padding:24px;'>"
                "<h3>Google авторизация завершена</h3>"
                "<p>Можно закрыть это окно и вернуться в CXEMA V7.</p>"
                "</body></html>"
            )
        )
    except Exception as exc:  # pragma: no cover
        message = str(exc)
        return HTMLResponse(
            status_code=400,
            content=(
                "<html><body style='font-family:sans-serif;padding:24px;'>"
                "<h3>Ошибка авторизации Google</h3>"
                f"<pre>{message}</pre>"
                "</body></html>"
            ),
        )
