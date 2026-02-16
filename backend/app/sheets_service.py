from __future__ import annotations

import json
import secrets
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AdjustmentType,
    ClientBillingAdjustment,
    ClientPaymentsPlan,
    ExpenseGroup,
    ExpenseItem,
    GoogleSheetLink,
    ItemMode,
    Project,
)
from .settings import settings
from .utils import gen_stable_id

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]
PREVIEW_CACHE_TTL_SECONDS = 30 * 60
_PREVIEW_CACHE: Dict[int, Dict[str, Any]] = {}
OAUTH_STATE_TTL_SECONDS = 10 * 60
_OAUTH_STATE_CACHE: Dict[str, float] = {}


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (_backend_root() / path).resolve()


def _mock_dir() -> Path:
    base = _resolve_path(settings.SHEETS_MOCK_DIR)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _mock_file(project_id: int) -> Path:
    return _mock_dir() / f"project_{project_id}.json"


def _token_file() -> Path:
    path = _resolve_path(settings.GOOGLE_TOKEN_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _client_secret_file() -> Path:
    return _resolve_path(settings.GOOGLE_CLIENT_SECRET_FILE)


def _round2(value: float) -> float:
    return round(float(value), 2)


def _sheet_url(spreadsheet_id: Optional[str]) -> Optional[str]:
    if not spreadsheet_id:
        return None
    if settings.SHEETS_MODE == "real":
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    return f"mock://{spreadsheet_id}"


def _project_or_404(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise ValueError("PROJECT_NOT_FOUND")
    return p


def _link_for_project(db: Session, project_id: int) -> Optional[GoogleSheetLink]:
    return db.execute(
        select(GoogleSheetLink).where(GoogleSheetLink.project_id == project_id)
    ).scalar_one_or_none()


def _ensure_link(db: Session, project_id: int) -> GoogleSheetLink:
    link = _link_for_project(db, project_id)
    if link:
        return link
    link = GoogleSheetLink(
        project_id=project_id,
        spreadsheet_id=f"mock-sheet-{project_id}",
        sheet_tab_name="PROJECT",
    )
    db.add(link)
    db.flush()
    return link


def _import_google_deps():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import Flow
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover
        raise ValueError("GOOGLE_LIBRARIES_NOT_INSTALLED") from exc
    return Credentials, Request, Flow, build


def _save_google_credentials(creds: Any) -> None:
    token_path = _token_file()
    token_path.write_text(creds.to_json(), encoding="utf-8")


def _cleanup_oauth_states() -> None:
    now = time.time()
    expired = [state for state, ts in _OAUTH_STATE_CACHE.items() if now - ts > OAUTH_STATE_TTL_SECONDS]
    for state in expired:
        _OAUTH_STATE_CACHE.pop(state, None)


def _register_oauth_state(state: str) -> None:
    _cleanup_oauth_states()
    _OAUTH_STATE_CACHE[state] = time.time()


def _consume_oauth_state(state: str) -> None:
    _cleanup_oauth_states()
    ts = _OAUTH_STATE_CACHE.get(state)
    if ts is None:
        raise ValueError("GOOGLE_OAUTH_STATE_INVALID")
    if time.time() - ts > OAUTH_STATE_TTL_SECONDS:
        _OAUTH_STATE_CACHE.pop(state, None)
        raise ValueError("GOOGLE_OAUTH_STATE_EXPIRED")
    _OAUTH_STATE_CACHE.pop(state, None)


def _load_google_credentials(required: bool = False) -> Optional[Any]:
    Credentials, Request, _, _ = _import_google_deps()

    token_path = _token_file()
    if not token_path.exists():
        if required:
            raise ValueError("GOOGLE_AUTH_REQUIRED")
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(token_path), GOOGLE_SCOPES)
    except Exception as exc:
        if required:
            raise ValueError("GOOGLE_TOKEN_INVALID") from exc
        return None

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_google_credentials(creds)
        except Exception as exc:
            if required:
                raise ValueError("GOOGLE_TOKEN_REFRESH_FAILED") from exc
            return None

    if not creds.valid:
        if required:
            raise ValueError("GOOGLE_AUTH_REQUIRED")
        return None

    return creds


def get_google_auth_status() -> Dict[str, Any]:
    secret_path = _client_secret_file()
    connected = False
    last_error: Optional[str] = None

    if settings.SHEETS_MODE == "real":
        try:
            connected = _load_google_credentials(required=False) is not None
        except Exception as exc:  # pragma: no cover
            last_error = str(exc)

    return {
        "mode": settings.SHEETS_MODE,
        "connected": connected,
        "client_secret_configured": secret_path.exists(),
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "token_file_path": str(_token_file()),
        "last_error": last_error,
    }


def start_google_oauth() -> Dict[str, str]:
    if settings.SHEETS_MODE != "real":
        raise ValueError("GOOGLE_AUTH_REAL_MODE_REQUIRED")

    secret_path = _client_secret_file()
    if not secret_path.exists():
        raise ValueError("GOOGLE_CLIENT_SECRET_FILE_NOT_FOUND")

    _, _, Flow, _ = _import_google_deps()
    flow = Flow.from_client_secrets_file(
        str(secret_path),
        scopes=GOOGLE_SCOPES,
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    _register_oauth_state(state)
    return {"auth_url": auth_url, "state": state}


def complete_google_oauth(state: str, code: str) -> Dict[str, Any]:
    if settings.SHEETS_MODE != "real":
        raise ValueError("GOOGLE_AUTH_REAL_MODE_REQUIRED")

    secret_path = _client_secret_file()
    if not secret_path.exists():
        raise ValueError("GOOGLE_CLIENT_SECRET_FILE_NOT_FOUND")

    _consume_oauth_state(state)

    _, _, Flow, _ = _import_google_deps()
    flow = Flow.from_client_secrets_file(
        str(secret_path),
        scopes=GOOGLE_SCOPES,
        state=state,
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
    )
    flow.fetch_token(code=code)
    _save_google_credentials(flow.credentials)
    return {"connected": True, "message": "GOOGLE_AUTH_CONNECTED"}


def _get_sheets_api_client() -> Any:
    creds = _load_google_credentials(required=True)
    _, _, _, build = _import_google_deps()
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _item_sheet_values(item: ExpenseItem, adjustment: Optional[ClientBillingAdjustment]) -> Dict[str, Any]:
    if item.mode == ItemMode.QTY_PRICE:
        qty = float(item.qty or 0.0)
        unit_price_full = float(adjustment.unit_price_full) if adjustment else float(item.unit_price_base or 0.0)
    else:
        qty = 1.0
        unit_price_full = float(adjustment.unit_price_full) if adjustment else float(item.base_total or 0.0)

    unit_price_billable = float(adjustment.unit_price_billable) if adjustment else unit_price_full
    adjustment_type = adjustment.adjustment_type.value if adjustment else AdjustmentType.DISCOUNT.value
    reason = adjustment.reason if adjustment else ""

    total_full = qty * unit_price_full
    total_billable = qty * unit_price_billable

    return {
        "qty": qty,
        "unit_price_full": unit_price_full,
        "unit_price_billable": unit_price_billable,
        "adjustment_type": adjustment_type,
        "reason": reason,
        "total_full": total_full,
        "total_billable": total_billable,
        "delta": total_full - total_billable,
    }


def _build_snapshot(db: Session, project_id: int) -> Dict[str, Any]:
    project = _project_or_404(db, project_id)

    groups = db.execute(
        select(ExpenseGroup).where(ExpenseGroup.project_id == project_id).order_by(ExpenseGroup.sort_order.asc(), ExpenseGroup.id.asc())
    ).scalars().all()
    group_name_by_id = {g.id: g.name for g in groups}

    items = db.execute(
        select(ExpenseItem).where(ExpenseItem.project_id == project_id).order_by(ExpenseItem.group_id.asc(), ExpenseItem.id.asc())
    ).scalars().all()
    item_ids = [it.id for it in items]
    adjustments = db.execute(
        select(ClientBillingAdjustment).where(ClientBillingAdjustment.expense_item_id.in_(item_ids))
    ).scalars().all() if item_ids else []
    adjustment_by_item_id = {adj.expense_item_id: adj for adj in adjustments}

    estimate_rows: List[Dict[str, Any]] = []
    for item in items:
        if not bool(getattr(item, "include_in_estimate", True)):
            continue
        sheet_vals = _item_sheet_values(item, adjustment_by_item_id.get(item.id))
        estimate_rows.append({
            "item_id": item.stable_item_id,
            "group": group_name_by_id.get(item.group_id, ""),
            "name": item.title,
            "qty": _round2(sheet_vals["qty"]),
            "unit_price_billable": _round2(sheet_vals["unit_price_billable"]),
            "adjustment_type": sheet_vals["adjustment_type"],
            "reason": sheet_vals["reason"],
            "total_billable": _round2(sheet_vals["total_billable"]),
            "unit_price_full": _round2(sheet_vals["unit_price_full"]),
            "total_full": _round2(sheet_vals["total_full"]),
            "delta": _round2(sheet_vals["delta"]),
        })

    payments = db.execute(
        select(ClientPaymentsPlan).where(ClientPaymentsPlan.project_id == project_id).order_by(ClientPaymentsPlan.pay_date.asc(), ClientPaymentsPlan.id.asc())
    ).scalars().all()
    payments_plan_rows = [{
        "pay_id": pay.stable_pay_id,
        "date": pay.pay_date.isoformat(),
        "amount": _round2(pay.amount),
        "note": pay.note,
    } for pay in payments]

    return {
        "meta": {
            "project_id": project.id,
            "project_title": project.title,
            "sheet_tab_name": "PROJECT",
            "mode": settings.SHEETS_MODE,
            "exported_at": datetime.utcnow().isoformat(),
            "instructions": "editable: qty, unit_price_billable, adjustment_type, reason, payments date/amount/note",
        },
        "estimate_rows": estimate_rows,
        "payments_plan_rows": payments_plan_rows,
    }


def _read_mock_snapshot(project_id: int) -> Dict[str, Any]:
    path = _mock_file(project_id)
    if not path.exists():
        raise ValueError("SHEET_NOT_PUBLISHED")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_cell(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _parse_real_sheet_values(values: List[List[Any]]) -> Dict[str, Any]:
    normalized = [list(row) + [""] * max(0, 11 - len(row)) for row in values]

    estimate_anchor_idx = None
    payments_anchor_idx = None
    for idx, row in enumerate(normalized):
        marker = _normalize_cell(row[0])
        if marker == "== ESTIMATE ==":
            estimate_anchor_idx = idx
        elif marker == "== PAYMENTS_PLAN ==":
            payments_anchor_idx = idx

    if estimate_anchor_idx is None or payments_anchor_idx is None or payments_anchor_idx <= estimate_anchor_idx:
        raise ValueError("SHEET_FORMAT_INVALID")

    estimate_rows: List[Dict[str, Any]] = []
    for idx in range(estimate_anchor_idx + 2, payments_anchor_idx):
        row = normalized[idx]
        if not any(_normalize_cell(v) for v in row[:11]):
            continue
        item_id = _normalize_cell(row[0])
        if not item_id:
            continue
        estimate_rows.append({
            "item_id": item_id,
            "group": _normalize_cell(row[1]),
            "name": _normalize_cell(row[2]),
            "qty": row[3],
            "unit_price_billable": row[4],
            "adjustment_type": _normalize_cell(row[5]),
            "reason": _normalize_cell(row[6]),
            "total_billable": row[7],
            "unit_price_full": row[8],
            "total_full": row[9],
            "delta": row[10],
        })

    payments_rows: List[Dict[str, Any]] = []
    for idx in range(payments_anchor_idx + 2, len(normalized)):
        row = normalized[idx]
        if not any(_normalize_cell(v) for v in row[:4]):
            continue
        payments_rows.append({
            "pay_id": _normalize_cell(row[0]),
            "date": _normalize_cell(row[1]),
            "amount": row[2],
            "note": _normalize_cell(row[3]),
        })

    return {
        "meta": {
            "sheet_tab_name": "PROJECT",
            "mode": "real",
            "imported_at": datetime.utcnow().isoformat(),
        },
        "estimate_rows": estimate_rows,
        "payments_plan_rows": payments_rows,
    }


def _read_real_snapshot(db: Session, project_id: int) -> Dict[str, Any]:
    link = _link_for_project(db, project_id)
    if not link or not link.spreadsheet_id:
        raise ValueError("SHEET_NOT_PUBLISHED")

    sheets = _get_sheets_api_client().spreadsheets()
    tab_name = link.sheet_tab_name or "PROJECT"
    result = sheets.values().get(
        spreadsheetId=link.spreadsheet_id,
        range=f"{tab_name}!A1:K400",
    ).execute()
    values = result.get("values", [])
    return _parse_real_sheet_values(values)


def _build_real_sheet_rows(snapshot: Dict[str, Any], project_title: str, now_iso: str) -> Dict[str, Any]:
    rows: List[List[Any]] = [
        ["PROJECT_TITLE:", project_title],
        ["LAST_PUBLISHED_AT:", now_iso],
        ["INSTRUCTIONS:", "Редактируйте только qty/price/adjustment/reason и блок платежей."],
        [],
        ["== ESTIMATE =="],
        ["item_id", "group", "name", "qty", "unit_price_billable", "adjustment_type", "reason", "total_billable", "unit_price_full", "total_full", "delta"],
    ]

    estimate_rows = snapshot.get("estimate_rows", [])
    estimate_start_row = 7
    for idx, row in enumerate(estimate_rows, start=estimate_start_row):
        rows.append([
            row.get("item_id", ""),
            row.get("group", ""),
            row.get("name", ""),
            row.get("qty", 0),
            row.get("unit_price_billable", 0),
            row.get("adjustment_type", AdjustmentType.DISCOUNT.value),
            row.get("reason", ""),
            f"=IFERROR(D{idx}*E{idx},0)",
            row.get("unit_price_full", 0),
            f"=IFERROR(D{idx}*I{idx},0)",
            f"=IFERROR(J{idx}-H{idx},0)",
        ])

    estimate_end_row = estimate_start_row + max(len(estimate_rows), 1) - 1

    rows.extend([[], []])
    payments_anchor_row = len(rows) + 1
    rows.append(["== PAYMENTS_PLAN =="])
    rows.append(["pay_id", "date", "amount", "note"])

    payments_rows = snapshot.get("payments_plan_rows", [])
    payments_start_row = len(rows) + 1
    for row in payments_rows:
        rows.append([
            row.get("pay_id", ""),
            row.get("date", ""),
            row.get("amount", 0),
            row.get("note", ""),
        ])

    payments_end_row = payments_start_row + max(len(payments_rows), 1) - 1

    return {
        "rows": rows,
        "estimate_start_row": estimate_start_row,
        "estimate_end_row": estimate_end_row,
        "payments_start_row": payments_start_row,
        "payments_end_row": payments_end_row,
        "payments_anchor_row": payments_anchor_row,
    }


def _ensure_real_spreadsheet_for_project(
    sheets_api: Any,
    project_title: str,
    spreadsheet_id: Optional[str],
) -> Tuple[str, int]:
    sheet_tab_name = "PROJECT"

    if not spreadsheet_id:
        created = sheets_api.create(
            body={
                "properties": {"title": f"Смета — {project_title}"},
                "sheets": [{"properties": {"title": sheet_tab_name}}],
            },
            fields="spreadsheetId",
        ).execute()
        spreadsheet_id = created["spreadsheetId"]

    metadata = sheets_api.get(spreadsheetId=spreadsheet_id).execute()
    for sh in metadata.get("sheets", []):
        props = sh.get("properties", {})
        if props.get("title") == sheet_tab_name:
            return spreadsheet_id, int(props.get("sheetId"))

    updated = sheets_api.batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {"addSheet": {"properties": {"title": sheet_tab_name}}}
            ]
        },
    ).execute()
    new_sheet_id = int(updated["replies"][0]["addSheet"]["properties"]["sheetId"])
    return spreadsheet_id, new_sheet_id


def _publish_real(db: Session, project_id: int) -> Dict[str, Any]:
    project = _project_or_404(db, project_id)
    link = _link_for_project(db, project_id)

    sheets_api = _get_sheets_api_client().spreadsheets()
    spreadsheet_id, sheet_id = _ensure_real_spreadsheet_for_project(
        sheets_api,
        project.title,
        link.spreadsheet_id if link else None,
    )

    snapshot = _build_snapshot(db, project_id)
    now = datetime.utcnow()
    sheet_payload = _build_real_sheet_rows(snapshot, project.title, now.isoformat())

    sheets_api.values().clear(
        spreadsheetId=spreadsheet_id,
        range="PROJECT!A1:K400",
        body={},
    ).execute()

    sheets_api.values().update(
        spreadsheetId=spreadsheet_id,
        range="PROJECT!A1",
        valueInputOption="USER_ENTERED",
        body={"values": sheet_payload["rows"]},
    ).execute()

    metadata = sheets_api.get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId),protectedRanges(protectedRangeId))",
    ).execute()
    existing_protected_ids: List[int] = []
    for sh in metadata.get("sheets", []):
        props = sh.get("properties", {})
        if int(props.get("sheetId", -1)) != sheet_id:
            continue
        for protected in sh.get("protectedRanges", []):
            if "protectedRangeId" in protected:
                existing_protected_ids.append(int(protected["protectedRangeId"]))

    requests: List[Dict[str, Any]] = []

    for protected_id in existing_protected_ids:
        requests.append({"deleteProtectedRange": {"protectedRangeId": protected_id}})

    requests.append(
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": 1,
                },
                "properties": {"hiddenByUser": True},
                "fields": "hiddenByUser",
            }
        }
    )

    requests.append(
        {
            "setDataValidation": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": sheet_payload["estimate_start_row"] - 1,
                    "endRowIndex": max(sheet_payload["estimate_end_row"], sheet_payload["estimate_start_row"]),
                    "startColumnIndex": 5,
                    "endColumnIndex": 6,
                },
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [
                            {"userEnteredValue": "DISCOUNT"},
                            {"userEnteredValue": "CREDIT_FROM_PREV"},
                            {"userEnteredValue": "CARRY_TO_NEXT"},
                        ],
                    },
                    "strict": True,
                    "showCustomUi": True,
                },
            }
        }
    )

    requests.append(
        {
            "addProtectedRange": {
                "protectedRange": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 400,
                        "startColumnIndex": 0,
                        "endColumnIndex": 11,
                    },
                    "warningOnly": False,
                    "description": "PROJECT protected areas (RO + structure)",
                    "unprotectedRanges": [
                        {
                            "sheetId": sheet_id,
                            "startRowIndex": sheet_payload["estimate_start_row"] - 1,
                            "endRowIndex": max(sheet_payload["estimate_end_row"], sheet_payload["estimate_start_row"]),
                            "startColumnIndex": 3,
                            "endColumnIndex": 7,
                        },
                        {
                            "sheetId": sheet_id,
                            "startRowIndex": sheet_payload["payments_start_row"] - 1,
                            "endRowIndex": 400,
                            "startColumnIndex": 1,
                            "endColumnIndex": 4,
                        },
                    ],
                }
            }
        }
    )

    sheets_api.batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()

    if not link:
        link = GoogleSheetLink(
            project_id=project_id,
            spreadsheet_id=spreadsheet_id,
            sheet_tab_name="PROJECT",
        )
        db.add(link)
    else:
        link.spreadsheet_id = spreadsheet_id
        link.sheet_tab_name = "PROJECT"

    link.last_published_at = now
    db.commit()
    db.refresh(link)

    return {
        "status": "published",
        "spreadsheet_id": spreadsheet_id,
        "sheet_url": _sheet_url(spreadsheet_id),
        "mock_file_path": None,
        "last_published_at": now,
        "estimate_rows": len(snapshot.get("estimate_rows", [])),
        "payments_plan_rows": len(snapshot.get("payments_plan_rows", [])),
    }


def _safe_float(value: Any, field: str, row_label: str, errors: List[str]) -> Optional[float]:
    normalized = value
    if isinstance(normalized, str):
        normalized = normalized.replace(" ", "").replace(",", ".")
    try:
        out = float(normalized)
    except (TypeError, ValueError):
        errors.append(f"{row_label}: {field}_INVALID")
        return None
    if out < 0:
        errors.append(f"{row_label}: {field}_NEGATIVE")
        return None
    return out


def _cache_preview(project_id: int, preview: Dict[str, Any], ops: Dict[str, Any]) -> str:
    token = secrets.token_urlsafe(18)
    _PREVIEW_CACHE[project_id] = {
        "token": token,
        "created_at": time.time(),
        "preview": preview,
        "ops": ops,
    }
    return token


def _take_cached_preview(project_id: int, preview_token: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    cached = _PREVIEW_CACHE.get(project_id)
    if not cached or cached.get("token") != preview_token:
        raise ValueError("PREVIEW_CONFIRM_REQUIRED")
    if time.time() - float(cached.get("created_at", 0)) > PREVIEW_CACHE_TTL_SECONDS:
        _PREVIEW_CACHE.pop(project_id, None)
        raise ValueError("PREVIEW_TOKEN_EXPIRED")
    _PREVIEW_CACHE.pop(project_id, None)
    return cached["preview"], cached["ops"]


def _compute_import_preview_for_snapshot(
    db: Session,
    project_id: int,
    snapshot: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    _project_or_404(db, project_id)

    items = db.execute(
        select(ExpenseItem).where(ExpenseItem.project_id == project_id)
    ).scalars().all()
    items_by_stable_id = {it.stable_item_id: it for it in items}
    adjustments = db.execute(
        select(ClientBillingAdjustment).where(ClientBillingAdjustment.expense_item_id.in_([it.id for it in items]))
    ).scalars().all() if items else []
    adjustment_by_item_id = {adj.expense_item_id: adj for adj in adjustments}

    plans = db.execute(
        select(ClientPaymentsPlan).where(ClientPaymentsPlan.project_id == project_id)
    ).scalars().all()
    plans_by_stable_id = {p.stable_pay_id: p for p in plans}

    valid_adjustments = {a.value for a in AdjustmentType}

    errors: List[str] = []
    items_updated: List[Dict[str, Any]] = []
    payments_updated: List[Dict[str, Any]] = []
    payments_new: List[Dict[str, Any]] = []

    item_ops: List[Dict[str, Any]] = []
    payment_update_ops: List[Dict[str, Any]] = []
    payment_new_ops: List[Dict[str, Any]] = []

    for idx, row in enumerate(snapshot.get("estimate_rows", []), start=1):
        row_label = f"ESTIMATE_ROW_{idx}"
        item_key = str(row.get("item_id", "")).strip()
        if not item_key:
            continue

        item = items_by_stable_id.get(item_key)
        if not item:
            errors.append(f"{row_label}: ITEM_NOT_FOUND:{item_key}")
            continue

        current = _item_sheet_values(item, adjustment_by_item_id.get(item.id))

        qty = _safe_float(row.get("qty", 0), "qty", row_label, errors)
        unit_price_billable = _safe_float(row.get("unit_price_billable", 0), "unit_price_billable", row_label, errors)
        if qty is None or unit_price_billable is None:
            continue

        adjustment_type_raw = str(row.get("adjustment_type") or "").strip().upper()
        full_unit_price = float(current["unit_price_full"])
        if not adjustment_type_raw:
            if round(float(unit_price_billable), 6) != round(full_unit_price, 6):
                errors.append(f"{row_label}: ADJUSTMENT_TYPE_REQUIRED")
                continue
            adjustment_type = AdjustmentType.DISCOUNT.value
        else:
            adjustment_type = adjustment_type_raw
            if adjustment_type not in valid_adjustments:
                errors.append(f"{row_label}: ADJUSTMENT_TYPE_INVALID")
                continue

        reason = str(row.get("reason") or "")
        changes: Dict[str, Dict[str, Any]] = {}

        if item.mode == ItemMode.QTY_PRICE:
            if round(float(current["qty"]), 6) != round(float(qty), 6):
                changes["qty"] = {"from": _round2(float(current["qty"])), "to": _round2(qty)}
        elif round(float(qty), 6) != 1.0:
            errors.append(f"{row_label}: QTY_FOR_SINGLE_TOTAL_MUST_BE_1")

        if round(float(current["unit_price_billable"]), 6) != round(float(unit_price_billable), 6):
            changes["unit_price_billable"] = {"from": _round2(float(current["unit_price_billable"])), "to": _round2(unit_price_billable)}

        if str(current["adjustment_type"]) != adjustment_type:
            changes["adjustment_type"] = {"from": str(current["adjustment_type"]), "to": adjustment_type}

        if str(current["reason"]) != reason:
            changes["reason"] = {"from": str(current["reason"]), "to": reason}

        if changes:
            items_updated.append({
                "item_id": item.stable_item_id,
                "title": item.title,
                "changes": changes,
            })
            item_ops.append({
                "db_item_id": item.id,
                "qty": qty,
                "unit_price_full": float(current["unit_price_full"]),
                "unit_price_billable": unit_price_billable,
                "adjustment_type": adjustment_type,
                "reason": reason,
            })

    for idx, row in enumerate(snapshot.get("payments_plan_rows", []), start=1):
        row_label = f"PAYMENT_ROW_{idx}"
        pay_id = str(row.get("pay_id", "")).strip()
        date_raw = str(row.get("date", "")).strip()
        amount = _safe_float(row.get("amount", 0), "amount", row_label, errors)
        if amount is None:
            continue
        note = str(row.get("note") or "")

        if not date_raw and not pay_id and amount == 0 and note == "":
            continue

        try:
            pay_date = date.fromisoformat(date_raw)
        except ValueError:
            errors.append(f"{row_label}: DATE_INVALID")
            continue

        if pay_id:
            plan = plans_by_stable_id.get(pay_id)
            if not plan:
                errors.append(f"{row_label}: PAY_ID_NOT_FOUND:{pay_id}")
                continue
            changes: Dict[str, Dict[str, Any]] = {}
            if plan.pay_date != pay_date:
                changes["pay_date"] = {"from": plan.pay_date.isoformat(), "to": pay_date.isoformat()}
            if round(float(plan.amount), 6) != round(float(amount), 6):
                changes["amount"] = {"from": _round2(plan.amount), "to": _round2(amount)}
            if plan.note != note:
                changes["note"] = {"from": plan.note, "to": note}
            if changes:
                payments_updated.append({"pay_id": pay_id, "changes": changes})
                payment_update_ops.append({
                    "db_payment_id": plan.id,
                    "pay_date": pay_date,
                    "amount": amount,
                    "note": note,
                })
        else:
            payments_new.append({
                "pay_date": pay_date.isoformat(),
                "amount": _round2(amount),
                "note": note,
            })
            payment_new_ops.append({
                "pay_date": pay_date,
                "amount": amount,
                "note": note,
            })

    public_preview = {
        "items_updated": items_updated,
        "payments_updated": payments_updated,
        "payments_new": payments_new,
        "errors": errors,
    }
    apply_ops = {
        "items": item_ops,
        "payments_updated": payment_update_ops,
        "payments_new": payment_new_ops,
    }
    return public_preview, apply_ops


def _compute_import_preview(db: Session, project_id: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if settings.SHEETS_MODE == "mock":
        snapshot = _read_mock_snapshot(project_id)
    elif settings.SHEETS_MODE == "real":
        snapshot = _read_real_snapshot(db, project_id)
    else:
        raise ValueError("SHEETS_MODE_INVALID")

    return _compute_import_preview_for_snapshot(db, project_id, snapshot)


def get_sheets_status(db: Session, project_id: int) -> Dict[str, Any]:
    _project_or_404(db, project_id)
    link = _link_for_project(db, project_id)
    return {
        "mode": settings.SHEETS_MODE,
        "spreadsheet_id": link.spreadsheet_id if link else None,
        "sheet_tab_name": link.sheet_tab_name if link else None,
        "sheet_url": _sheet_url(link.spreadsheet_id if link else None),
        "mock_file_path": str(_mock_file(project_id)) if settings.SHEETS_MODE == "mock" else None,
        "last_published_at": link.last_published_at if link else None,
        "last_imported_at": link.last_imported_at if link else None,
    }


def publish_to_sheets(db: Session, project_id: int) -> Dict[str, Any]:
    _project_or_404(db, project_id)

    if settings.SHEETS_MODE == "mock":
        link = _ensure_link(db, project_id)
        snapshot = _build_snapshot(db, project_id)

        now = datetime.utcnow()
        link.last_published_at = now
        db.commit()
        db.refresh(link)

        snapshot["meta"]["last_published_at"] = now.isoformat()
        path = _mock_file(project_id)
        with path.open("w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

        return {
            "status": "published",
            "spreadsheet_id": link.spreadsheet_id,
            "sheet_url": _sheet_url(link.spreadsheet_id),
            "mock_file_path": str(path),
            "last_published_at": now,
            "estimate_rows": len(snapshot["estimate_rows"]),
            "payments_plan_rows": len(snapshot["payments_plan_rows"]),
        }

    if settings.SHEETS_MODE == "real":
        return _publish_real(db, project_id)

    raise ValueError("SHEETS_MODE_INVALID")


def preview_import_from_sheets(db: Session, project_id: int) -> Dict[str, Any]:
    preview, ops = _compute_import_preview(db, project_id)
    preview_token = _cache_preview(project_id, preview, ops)
    return {
        "preview_token": preview_token,
        **preview,
    }


def apply_import_from_sheets(db: Session, project_id: int, preview_token: str) -> Dict[str, Any]:
    preview, ops = _take_cached_preview(project_id, preview_token)

    applied_items = 0
    for op in ops["items"]:
        item = db.get(ExpenseItem, int(op["db_item_id"]))
        if not item:
            continue

        if item.mode == ItemMode.QTY_PRICE:
            item.qty = float(op["qty"])
            if item.unit_price_base is not None:
                qty = float(item.qty)
                unit = float(item.unit_price_base)
                item.base_total = unit if qty == 0 else qty * unit

        adj = db.execute(
            select(ClientBillingAdjustment).where(ClientBillingAdjustment.expense_item_id == item.id)
        ).scalar_one_or_none()
        if not adj:
            adj = ClientBillingAdjustment(
                expense_item_id=item.id,
                unit_price_full=float(op["unit_price_full"]),
                unit_price_billable=float(op["unit_price_billable"]),
                adjustment_type=AdjustmentType(op["adjustment_type"]),
                reason=str(op["reason"]),
            )
            db.add(adj)
        else:
            adj.unit_price_full = float(op["unit_price_full"])
            adj.unit_price_billable = float(op["unit_price_billable"])
            adj.adjustment_type = AdjustmentType(op["adjustment_type"])
            adj.reason = str(op["reason"])

        applied_items += 1

    applied_payments_updated = 0
    for op in ops["payments_updated"]:
        rec = db.get(ClientPaymentsPlan, int(op["db_payment_id"]))
        if not rec:
            continue
        rec.pay_date = op["pay_date"]
        rec.amount = float(op["amount"])
        rec.note = str(op["note"])
        applied_payments_updated += 1

    applied_payments_new = 0
    for op in ops["payments_new"]:
        rec = ClientPaymentsPlan(
            stable_pay_id=gen_stable_id("pay"),
            project_id=project_id,
            pay_date=op["pay_date"],
            amount=float(op["amount"]),
            note=str(op["note"]),
        )
        db.add(rec)
        applied_payments_new += 1

    imported_at: Optional[datetime] = None
    if applied_items or applied_payments_updated or applied_payments_new:
        link = _ensure_link(db, project_id)
        imported_at = datetime.utcnow()
        link.last_imported_at = imported_at

    db.commit()

    return {
        "applied_items": applied_items,
        "applied_payments_updated": applied_payments_updated,
        "applied_payments_new": applied_payments_new,
        "errors": preview["errors"],
        "imported_at": imported_at,
    }
