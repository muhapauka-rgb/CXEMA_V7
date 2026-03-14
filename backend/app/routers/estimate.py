from __future__ import annotations

import atexit
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
from html import escape
from io import BytesIO
import re
import threading
import time
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from urllib.parse import quote

from ..db import get_db
from ..models import ClientBillingAdjustment, ClientPaymentsPlan, ExpenseGroup, ExpenseItem, ItemMode, Project
from ..sheets_service import _import_google_deps, _load_google_credentials
from ..utils import get_global_usn_settings

router = APIRouter(prefix="/api/projects", tags=["estimate"])

_DRIVE_FOLDER_ID_RE = re.compile(r"/folders/([a-zA-Z0-9_-]+)")
_DRIVE_ID_QUERY_RE = re.compile(r"[?&]id=([a-zA-Z0-9_-]+)")
_PDF_BROWSER_LOCK = threading.Lock()
_PDF_CACHE_LOCK = threading.Lock()
_PLAYWRIGHT: Optional[Any] = None
_PLAYWRIGHT_BROWSER: Optional[Any] = None
_PDF_HTML_CACHE: Dict[str, tuple[float, bytes]] = {}
_PDF_CACHE_TTL_SECONDS = 120.0
_PDF_CACHE_MAX_ENTRIES = 24


def _safe_num(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _fmt_money(value: float) -> str:
    return f"{float(value or 0.0):,.2f}".replace(",", " ").replace(".", ",")


def _fmt_money_no_dec(value: Any) -> str:
    try:
        rounded = Decimal(str(value if value is not None else 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{int(rounded):,}".replace(",", " ")
    except Exception:
        return f"{int(round(_safe_num(value))):,}".replace(",", " ")


def _fmt_plain(value: Any) -> str:
    if value is None:
        return "—"
    text = str(value).strip()
    return text or "—"


def _fmt_date(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return value.strftime("%Y-%m-%d")
    except Exception:
        return str(value)


def _fmt_date_long(value: Any) -> str:
    if value is None:
        return "—"
    months = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    dt_obj: Optional[date] = None
    if isinstance(value, datetime):
        dt_obj = value.date()
    elif isinstance(value, date):
        dt_obj = value
    else:
        try:
            dt_obj = datetime.strptime(str(value), "%Y-%m-%d").date()
        except Exception:
            return str(value)
    if not dt_obj:
        return "—"
    return f"{dt_obj.day} {months[dt_obj.month - 1]} {dt_obj.year}"


def _fmt_generated_at(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        text = str(value).strip()
        if not text:
            return "—"
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return text
    return dt.strftime("%d.%m.%Y %H:%M")


def _item_base_total(item: ExpenseItem) -> float:
    base = _safe_num(item.base_total)
    if item.mode == ItemMode.QTY_PRICE and item.unit_price_base is not None:
        qty = _safe_num(item.qty)
        unit = _safe_num(item.unit_price_base)
        return unit if qty == 0 else qty * unit
    return base


def _percent_amount(base: float, percent: float) -> float:
    value = _safe_num(base)
    p = _safe_num(percent)
    if value <= 0 or p <= 0:
        return 0.0
    return value * p / 100.0


def _parse_group_ids(raw: Optional[str]) -> Set[int]:
    if not raw:
        return set()
    if not isinstance(raw, str):
        raw = str(raw)
    out: Set[int] = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            value = int(token)
        except Exception:
            continue
        if value > 0:
            out.add(value)
    return out


def _extract_drive_folder_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    folder_match = _DRIVE_FOLDER_ID_RE.search(raw)
    if folder_match:
        return folder_match.group(1)

    query_match = _DRIVE_ID_QUERY_RE.search(raw)
    if query_match:
        return query_match.group(1)

    # If user provided folder id directly.
    if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", raw):
        return raw
    return None


def _resolve_drive_folder_id(drive_api: Any, project: Project) -> Optional[str]:
    direct = _extract_drive_folder_id(project.google_drive_folder) or _extract_drive_folder_id(project.google_drive_url)
    if direct:
        return direct

    folder_name = (project.google_drive_folder or "").strip()
    if not folder_name:
        return None
    escaped_name = folder_name.replace("'", "''")
    try:
        out = drive_api.files().list(
            q=(
                "mimeType='application/vnd.google-apps.folder' "
                f"and name='{escaped_name}' and trashed=false"
            ),
            fields="files(id,name)",
            pageSize=1,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
    except Exception:
        return None
    files = out.get("files", [])
    if not files:
        return None
    return str(files[0].get("id") or "") or None


def _escape_drive_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _upload_or_replace_pdf_in_drive(
    drive_api: Any,
    folder_id: Optional[str],
    file_name: str,
    pdf_bytes: bytes,
) -> Dict[str, Any]:
    try:
        from googleapiclient.http import MediaInMemoryUpload
    except Exception as exc:
        raise ValueError("GOOGLE_LIBRARIES_NOT_INSTALLED") from exc

    safe_name = _escape_drive_query_value(file_name)
    query = (
        f"name='{safe_name}' and mimeType='application/pdf' and trashed=false"
    )
    if folder_id:
        safe_folder = _escape_drive_query_value(folder_id)
        query = f"'{safe_folder}' in parents and {query}"
    else:
        query = f"'root' in parents and {query}"

    existing = drive_api.files().list(
        q=query,
        fields="files(id,name,parents,modifiedTime,webViewLink,webContentLink)",
        orderBy="modifiedTime desc",
        pageSize=1,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute().get("files", [])

    media = MediaInMemoryUpload(pdf_bytes, mimetype="application/pdf", resumable=False)
    if existing:
        target = existing[0]
        file_id = target.get("id")
        update_kwargs: Dict[str, Any] = {
            "fileId": file_id,
            "body": {"name": file_name},
            "media_body": media,
            "fields": "id,name,webViewLink,webContentLink,parents",
            "supportsAllDrives": True,
        }
        if folder_id:
            current_parents = [str(p) for p in (target.get("parents") or []) if p]
            remove_parents = ",".join([p for p in current_parents if p != folder_id])
            update_kwargs["addParents"] = folder_id
            if remove_parents:
                update_kwargs["removeParents"] = remove_parents
        return drive_api.files().update(**update_kwargs).execute()

    metadata: Dict[str, Any] = {
        "name": file_name,
        "mimeType": "application/pdf",
    }
    if folder_id:
        metadata["parents"] = [folder_id]
    return drive_api.files().create(
        body=metadata,
        media_body=media,
        fields="id,name,webViewLink,webContentLink,parents",
        supportsAllDrives=True,
    ).execute()


def _estimate_pdf_file_name(project_title: Optional[str]) -> str:
    raw = str(project_title or "").strip()
    parts = [p for p in re.split(r"\s+", raw) if p]
    first_two = " ".join(parts[:2]).strip()
    base = first_two or "Проект"
    base = re.sub(r"[\\/:*?\"<>|]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return f"Смета - {base}.pdf"


def _drive_web_view_link(created: Dict[str, Any]) -> Optional[str]:
    direct = str(created.get("webViewLink") or "").strip()
    if direct:
        return direct
    file_id = str(created.get("id") or "").strip()
    if file_id:
        return f"https://drive.google.com/file/d/{file_id}/view"
    return None


def _project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    return project


def _render_estimate_pdf(payload: dict[str, Any]) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except Exception as exc:
        raise ValueError("PDF_LIBRARIES_NOT_INSTALLED") from exc

    font_regular = "Helvetica"
    font_bold = "Helvetica-Bold"
    font_table = "Courier"
    font_candidates = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for font_path in font_candidates:
        try:
            pdfmetrics.registerFont(TTFont("CXEMASans", font_path))
            pdfmetrics.registerFont(TTFont("CXEMASans-Bold", font_path))
            font_regular = "CXEMASans"
            font_bold = "CXEMASans-Bold"
            font_table = "CXEMASans"
            break
        except Exception:
            continue

    project = payload["project"]
    expense_groups = payload.get("expense_groups", [])
    payments = payload.get("payments_plan", [])
    totals = payload["totals"]

    line = colors.HexColor("#cfcfcf")
    bg_header = colors.black
    bg_muted = colors.HexColor("#f0f0f0")
    bg_sum = colors.HexColor("#fafafa")

    def row_h(base: float, k: float) -> float:
        return max(base * k, 8.0)

    n_payment_rows = max(1, len(payments))
    n_group_gaps = max(0, len(expense_groups) - 1)
    n_expense_rows = 0
    for g in expense_groups:
        n_expense_rows += 1  # group title
        n_expense_rows += len(g.get("rows") or [])
        if _safe_num(g.get("agency_amount")) > 0:
            n_expense_rows += 1
        n_expense_rows += 1  # group total
    if _safe_num(totals.get("common_agency_amount")) > 0:
        n_expense_rows += 1

    page_w, page_h = landscape(A4)
    margin = 8 * mm
    content_h = page_h - 2 * margin

    expenses_table_h = 22 + 22 + 16 + (n_expense_rows * 20) + (n_group_gaps * 42)
    payments_table_h = 22 + 22 + (n_payment_rows * 20)
    totals_block_h = (3 * 40) + (2 * 8)
    required_h = 24 + 20 + 40 + 14 + expenses_table_h + 14 + totals_block_h + 14 + payments_table_h
    k = min(1.0, content_h / max(required_h, 1))

    h_title = row_h(24, k)
    h_after_title = row_h(20, k)
    h_card = row_h(40, k)
    h_after_cards = row_h(14, k)
    h_panel_h = row_h(22, k)
    h_head = row_h(22, k)
    h_header_gap = row_h(16, k)
    h_row = row_h(20, k)
    h_group_gap = row_h(42, k)
    h_after_expenses = row_h(14, k)
    h_total_card = row_h(40, k)
    h_totals_gap = row_h(8, k)
    h_after_totals = row_h(14, k)

    # Base typography: keep one base size for layout,
    # then lift only top summary cards (+2 for labels, +5 for values).
    f_base = 11.0
    f_title = f_base
    f_meta = f_base
    f_label = f_base
    f_value = f_base
    f_tbl_h = f_base
    f_tbl = f_base
    f_top_label = f_base + 2.0
    f_top_value = f_base + 5.0

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    c.setTitle(f"Смета — {project.get('title', '')}")
    c.setFillColor(colors.white)
    c.rect(0, 0, page_w, page_h, stroke=0, fill=1)

    x0 = margin
    y_top = page_h - margin
    content_w = page_w - (2 * margin)
    gap = row_h(8, k)

    def rect_top(
        x: float,
        y: float,
        w: float,
        h: float,
        fill_color: Any = None,
        stroke_color: Any = line,
        stroke_width: float = 0.8,
    ) -> None:
        if fill_color is not None:
            c.setFillColor(fill_color)
        else:
            c.setFillColor(colors.white)
        c.setStrokeColor(stroke_color)
        c.setLineWidth(stroke_width)
        c.rect(x, y - h, w, h, stroke=1, fill=1)

    def draw_text_left(
        x: float,
        y: float,
        h: float,
        text: str,
        font_name: str,
        font_size: float,
        color: Any = colors.black,
        pad: float = 6.0,
    ) -> None:
        c.setFillColor(color)
        c.setFont(font_name, font_size)
        base = y - (h + font_size) / 2 + 2
        c.drawString(x + pad, base, text)

    def draw_text_center(
        x: float,
        y: float,
        w: float,
        h: float,
        text: str,
        font_name: str,
        font_size: float,
        color: Any = colors.black,
    ) -> None:
        c.setFillColor(color)
        c.setFont(font_name, font_size)
        base = y - (h + font_size) / 2 + 2
        tw = c.stringWidth(text, font_name, font_size)
        c.drawString(x + (w - tw) / 2, base, text)

    def draw_text_right(
        x: float,
        y: float,
        w: float,
        h: float,
        text: str,
        font_name: str,
        font_size: float,
        color: Any = colors.black,
        pad: float = 6.0,
    ) -> None:
        c.setFillColor(color)
        c.setFont(font_name, font_size)
        base = y - (h + font_size) / 2 + 2
        c.drawRightString(x + w - pad, base, text)

    project_title = _fmt_plain(project.get("title"))
    generated_at = _fmt_generated_at(project.get("generated_at"))
    c.setFillColor(colors.black)
    c.setFont(font_bold, f_title)
    c.drawString(x0, y_top - f_title, project_title)
    c.setFillColor(colors.HexColor("#555555"))
    c.setFont(font_regular, f_meta)
    c.drawRightString(x0 + content_w, y_top - f_meta, f"Сформировано: {generated_at}")
    y = y_top - h_title - h_after_title

    card_w = (content_w - (2 * gap)) / 3.0
    kpi = [
        ("Стоимость проекта", _fmt_money(project.get("project_price_total", 0.0))),
        ("Расходы на сегодня", _fmt_money(totals.get("expenses_today", 0.0))),
        ("Предстоящие оплаты", _fmt_money(totals.get("payments_upcoming_total", 0.0))),
    ]
    for i, (label, value) in enumerate(kpi):
        x = x0 + i * (card_w + gap)
        rect_top(x, y, card_w, h_card, fill_color=colors.white, stroke_color=line)
        c.setFillColor(colors.HexColor("#555555"))
        c.setFont(font_regular, f_top_label)
        c.drawString(x + 6, y - f_top_label - 6, label)
        c.setFillColor(colors.black)
        c.setFont(font_bold, f_top_value)
        c.drawString(x + 6, y - h_card + 8, value)
    y -= h_card + h_after_cards

    exp_x = x0
    exp_w = content_w
    exp_cols = [exp_w * 0.53, exp_w * 0.09, exp_w * 0.19, exp_w * 0.19]
    rect_top(exp_x, y, exp_w, h_panel_h, fill_color=bg_header, stroke_color=bg_header)
    draw_text_left(exp_x, y, h_panel_h, "Расходы", font_bold, f_tbl_h, colors.white, 8)
    y -= h_panel_h

    x = exp_x
    headers = ["Статья", "Шт", "Цена за ед", "Сумма"]
    for i, w in enumerate(exp_cols):
        rect_top(x, y, w, h_head, fill_color=bg_muted, stroke_color=line)
        if i == 0:
            draw_text_left(x, y, h_head, headers[i], font_bold, f_tbl_h, colors.HexColor("#202020"), 6)
        elif i == 1:
            draw_text_center(x, y, w, h_head, headers[i], font_bold, f_tbl_h, colors.HexColor("#202020"))
        else:
            draw_text_right(x, y, w, h_head, headers[i], font_bold, f_tbl_h, colors.HexColor("#202020"), 6)
        x += w
    y -= h_head + h_header_gap

    agency_percent = _fmt_money(project.get("agency_fee_percent", 0)).replace(",00", "")
    for idx, group in enumerate(expense_groups):
        rect_top(exp_x, y, exp_w, h_row, fill_color=bg_header, stroke_color=bg_header)
        draw_text_left(exp_x, y, h_row, _fmt_plain(group.get("group_name")), font_bold, f_tbl, colors.white, 6)
        y -= h_row

        for row in group.get("rows") or []:
            x = exp_x
            title = str(row.get("title") or "")
            if row.get("is_subitem"):
                title = f"↳ {title}"
            vals = [
                title,
                "" if row.get("qty") is None else _fmt_money(row.get("qty")).replace(",00", ""),
                "" if row.get("unit_price") is None else _fmt_money(row.get("unit_price")),
                _fmt_money(row.get("sum")),
            ]
            for i, w in enumerate(exp_cols):
                rect_top(x, y, w, h_row, fill_color=colors.white, stroke_color=line)
                if i == 0:
                    draw_text_left(x, y, h_row, vals[i], font_table, f_tbl, colors.black, 6)
                elif i == 1:
                    draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
                else:
                    draw_text_right(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black, 6)
                x += w
            y -= h_row

        agency_amount = _safe_num(group.get("agency_amount"))
        if agency_amount > 0:
            x = exp_x
            vals = [f"Агентские ({agency_percent}%)", "", "", _fmt_money(agency_amount)]
            for i, w in enumerate(exp_cols):
                rect_top(x, y, w, h_row, fill_color=bg_sum, stroke_color=line)
                if i == 0:
                    draw_text_left(x, y, h_row, vals[i], font_bold, f_tbl, colors.black, 6)
                elif i == 1:
                    draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
                else:
                    draw_text_right(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black, 6)
                x += w
            y -= h_row

        x = exp_x
        vals = ["Итого", "", "", _fmt_money(group.get("total_with_agency", 0.0))]
        for i, w in enumerate(exp_cols):
            rect_top(x, y, w, h_row, fill_color=bg_sum, stroke_color=line)
            if i == 0:
                draw_text_left(x, y, h_row, vals[i], font_bold, f_tbl, colors.black, 6)
            elif i == 1:
                draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
            else:
                draw_text_right(x, y, w, h_row, vals[i], font_bold if i == 3 else font_table, f_tbl, colors.black, 6)
            x += w
        y -= h_row

        if idx < len(expense_groups) - 1:
            y -= h_group_gap

    common_agency_amount = _safe_num(totals.get("common_agency_amount"))
    if common_agency_amount > 0:
        x = exp_x
        vals = [f"Агентские ({agency_percent}%)", "", "", _fmt_money(common_agency_amount)]
        for i, w in enumerate(exp_cols):
            rect_top(x, y, w, h_row, fill_color=bg_sum, stroke_color=line)
            if i == 0:
                draw_text_left(x, y, h_row, vals[i], font_bold, f_tbl, colors.black, 6)
            elif i == 1:
                draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
            else:
                draw_text_right(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black, 6)
            x += w
        y -= h_row

    y -= h_after_expenses

    total_card_w = min(content_w * 0.34, 100 * mm)
    total_x = x0 + content_w - total_card_w
    totals_cards = [
        ("Сумма (до УСН)", _fmt_money(totals.get("expenses_before_usn", 0.0))),
        (f"УСН ({_fmt_money(totals.get('usn_rate_percent', 0.0)).replace(',00', '')}%)", _fmt_money(totals.get("usn_amount", 0.0))),
        ("Сумма с УСН", _fmt_money(totals.get("expenses_with_usn", 0.0))),
    ]
    for idx, (label, value) in enumerate(totals_cards):
        rect_top(total_x, y, total_card_w, h_total_card, fill_color=colors.white, stroke_color=line)
        c.setFillColor(colors.HexColor("#555555"))
        c.setFont(font_regular, f_label)
        c.drawString(total_x + 6, y - f_label - 6, label)
        c.setFillColor(colors.black)
        c.setFont(font_bold, f_value)
        c.drawString(total_x + 6, y - h_total_card + 8, value)
        y -= h_total_card
        if idx < len(totals_cards) - 1:
            y -= h_totals_gap

    y -= h_after_totals

    pay_x = exp_x
    pay_w = exp_w
    pay_cols = [pay_w * 0.48, pay_w * 0.32, pay_w * 0.20]
    rect_top(pay_x, y, pay_w, h_panel_h, fill_color=bg_header, stroke_color=bg_header)
    draw_text_left(pay_x, y, h_panel_h, "План по оплатам", font_bold, f_tbl_h, colors.white, 8)
    y -= h_panel_h

    x = pay_x
    pay_headers = ["Дата оплаты", "Сумма", "Статус"]
    for i, w in enumerate(pay_cols):
        rect_top(x, y, w, h_head, fill_color=bg_muted, stroke_color=line)
        if i == 0:
            draw_text_center(x, y, w, h_head, pay_headers[i], font_bold, f_tbl_h, colors.HexColor("#202020"))
        elif i == 1:
            draw_text_right(x, y, w, h_head, pay_headers[i], font_bold, f_tbl_h, colors.HexColor("#202020"), 6)
        else:
            draw_text_center(x, y, w, h_head, pay_headers[i], font_bold, f_tbl_h, colors.HexColor("#202020"))
        x += w
    y -= h_head

    payment_rows = payments or [{"pay_date": None, "amount": "", "status": "Нет оплат"}]
    for row in payment_rows:
        x = pay_x
        vals = [
            _fmt_date_long(row.get("pay_date")),
            _fmt_money(row.get("amount")) if row.get("amount") not in {"", None} else "",
            _fmt_plain(row.get("status")),
        ]
        for i, w in enumerate(pay_cols):
            rect_top(x, y, w, h_row, fill_color=colors.white, stroke_color=line)
            if i == 0:
                draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
            elif i == 1:
                draw_text_right(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black, 6)
            else:
                draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
            x += w
        y -= h_row

    c.save()
    return buf.getvalue()


def _estimate_payload(
    db: Session,
    project_id: int,
    group_agency_ids: Optional[Set[int]] = None,
    common_agency_enabled: bool = False,
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    groups = db.execute(
        select(ExpenseGroup)
        .where(ExpenseGroup.project_id == project_id)
        .order_by(ExpenseGroup.sort_order.asc(), ExpenseGroup.id.asc())
    ).scalars().all()
    items = db.execute(
        select(ExpenseItem)
        .where(ExpenseItem.project_id == project_id)
        .order_by(ExpenseItem.group_id.asc(), ExpenseItem.id.asc())
    ).scalars().all()
    plans = db.execute(
        select(ClientPaymentsPlan)
        .where(ClientPaymentsPlan.project_id == project_id)
        .order_by(ClientPaymentsPlan.pay_date.asc(), ClientPaymentsPlan.id.asc())
    ).scalars().all()

    adjustments = db.execute(
        select(ClientBillingAdjustment).where(
            ClientBillingAdjustment.expense_item_id.in_([int(it.id) for it in items])
        )
    ).scalars().all() if items else []
    adjustment_by_item_id = {int(adj.expense_item_id): adj for adj in adjustments}

    group_name_by_id = {int(g.id): g.name for g in groups}
    item_by_id = {int(it.id): it for it in items}

    today = date.today()

    expense_rows: list[dict[str, Any]] = []
    expense_rows_by_group: dict[int, list[dict[str, Any]]] = {int(g.id): [] for g in groups}
    group_totals: dict[int, float] = {int(g.id): 0.0 for g in groups}
    group_totals_today: dict[int, float] = {int(g.id): 0.0 for g in groups}
    group_last_date: dict[int, Optional[date]] = {int(g.id): None for g in groups}
    expenses_total = 0.0
    expenses_today = 0.0
    for it in items:
        if not bool(getattr(it, "include_in_estimate", True)):
            continue
        adj = adjustment_by_item_id.get(int(it.id))
        discount_enabled = bool(adj.discount_enabled) if adj else False
        discount_amount = _safe_num(adj.discount_amount) if discount_enabled else 0.0
        base = _item_base_total(it)
        extra = _safe_num(it.extra_profit_amount) if bool(it.extra_profit_enabled) else 0.0
        row_total = base + extra - discount_amount
        gid = int(it.group_id)
        expenses_total += row_total
        group_totals[gid] = _safe_num(group_totals.get(gid, 0.0)) + row_total
        item_date = it.planned_pay_date if isinstance(it.planned_pay_date, date) else None
        if item_date and item_date <= today:
            expenses_today += row_total
            group_totals_today[gid] = _safe_num(group_totals_today.get(gid, 0.0)) + row_total
        last_dt = group_last_date.get(gid)
        if item_date and (last_dt is None or item_date > last_dt):
            group_last_date[gid] = item_date

        parent_title = ""
        is_subitem = False
        if it.parent_item_id is not None:
            parent = item_by_id.get(int(it.parent_item_id))
            if parent:
                parent_title = parent.title
                is_subitem = True

        row_payload = {
            "id": int(it.id),
            "group_id": gid,
            "group": group_name_by_id.get(gid, ""),
            "title": it.title,
            "parent_title": parent_title,
            "is_subitem": is_subitem,
            "date": _fmt_date(it.planned_pay_date),
            "qty": None if it.qty is None else _safe_num(it.qty),
            "unit_price": None if it.unit_price_base is None else _safe_num(it.unit_price_base),
            "sum": row_total,
        }
        expense_rows.append(row_payload)
        expense_rows_by_group.setdefault(gid, []).append(row_payload)

    payments_rows: list[dict[str, Any]] = []
    payments_total = 0.0
    payments_upcoming_total = 0.0
    for pay in plans:
        amount = _safe_num(pay.amount)
        payments_total += amount
        pay_date = pay.pay_date if isinstance(pay.pay_date, date) else None
        status = "План"
        if pay_date and pay_date <= today:
            status = "Факт"
        if pay_date and pay_date > today:
            payments_upcoming_total += amount
        payments_rows.append(
            {
                "id": int(pay.id),
                "pay_date": _fmt_date(pay.pay_date),
                "amount": amount,
                "note": pay.note or "",
                "status": status,
            }
        )

    agency_percent = _safe_num(project.agency_fee_percent)
    selected_group_agencies = group_agency_ids or set()
    group_summaries: list[dict[str, Any]] = []
    expense_groups: list[dict[str, Any]] = []
    group_agency_total = 0.0
    group_agency_today_total = 0.0
    for g in groups:
        gid = int(g.id)
        base_total = _safe_num(group_totals.get(gid, 0.0))
        agency_enabled = gid in selected_group_agencies
        agency_amount = _percent_amount(base_total, agency_percent) if agency_enabled else 0.0
        agency_today = 0.0
        if agency_enabled:
            last_dt = group_last_date.get(gid)
            if last_dt and last_dt <= today:
                agency_today = agency_amount
        group_agency_total += agency_amount
        group_agency_today_total += agency_today
        if base_total == 0 and not agency_enabled:
            continue
        summary = {
            "group_id": gid,
            "group_name": g.name,
            "base_total": base_total,
            "agency_enabled": agency_enabled,
            "agency_amount": agency_amount,
            "total_with_agency": base_total + agency_amount,
            "today_total": _safe_num(group_totals_today.get(gid, 0.0)) + agency_today,
        }
        group_summaries.append(summary)
        expense_groups.append(
            {
                "group_id": gid,
                "group_name": g.name,
                "rows": expense_rows_by_group.get(gid, []),
                "base_total": base_total,
                "agency_enabled": agency_enabled,
                "agency_amount": agency_amount,
                "total_with_agency": base_total + agency_amount,
            }
        )

    common_agency_amount = (
        _percent_amount(expenses_total, agency_percent)
        if common_agency_enabled
        else 0.0
    )
    common_agency_today = 0.0
    if common_agency_enabled and plans:
        pay_dates = [p.pay_date for p in plans if isinstance(p.pay_date, date)]
        if pay_dates and max(pay_dates) <= today:
            common_agency_today = common_agency_amount
    expenses_today += group_agency_today_total + common_agency_today
    expenses_before_usn = expenses_total + group_agency_total + common_agency_amount
    _usn_mode, usn_rate = get_global_usn_settings(db)
    usn_amount = _percent_amount(expenses_before_usn, usn_rate)
    expenses_with_usn = expenses_before_usn + usn_amount

    return {
        "project": {
            "id": int(project.id),
            "title": project.title,
            "organization": project.client_name or "",
            "email": project.client_email or "",
            "phone": project.client_phone or "",
            "agency_fee_percent": _safe_num(project.agency_fee_percent),
            "project_price_total": _safe_num(project.project_price_total),
            "generated_at": datetime.utcnow().isoformat(),
        },
        "expenses": expense_rows,
        "expense_groups": expense_groups,
        "group_summary": group_summaries,
        "payments_plan": payments_rows,
        "totals": {
            "expenses_total": expenses_total,
            "expenses_today": expenses_today,
            "group_agency_total": group_agency_total,
            "common_agency_amount": common_agency_amount,
            "expenses_before_usn": expenses_before_usn,
            "usn_rate_percent": usn_rate,
            "usn_amount": usn_amount,
            "expenses_with_usn": expenses_with_usn,
            "payments_plan_total": payments_total,
            "payments_upcoming_total": payments_upcoming_total,
            "balance_before_usn": payments_total - expenses_before_usn,
            "balance_with_usn": payments_total - expenses_with_usn,
        },
    }


def _render_estimate_html(payload: dict[str, Any]) -> str:
    project = payload["project"]
    expense_groups = payload.get("expense_groups", [])
    payments = payload["payments_plan"]
    totals = payload["totals"]

    rows_payments = []
    for row in payments:
        date = escape(_fmt_date_long(row["pay_date"]))
        amount = escape(_fmt_money(row["amount"]))
        status = escape(_fmt_plain(row.get("status")))
        rows_payments.append(
            f"""
            <tr>
              <td class="center">{date}</td>
              <td class="num strong">{amount}</td>
              <td class="center">{status}</td>
            </tr>
            """
        )
    if not rows_payments:
        rows_payments.append('<tr><td colspan="3" class="empty">Нет оплат</td></tr>')

    agency_percent = escape(_fmt_money(project.get("agency_fee_percent", 0)).replace(",00", ""))
    common_agency_amount = _safe_num(totals.get("common_agency_amount"))
    expense_rows: list[str] = []
    for group_idx, group in enumerate(expense_groups):
        group_name = escape(_fmt_plain(group.get("group_name")))
        expense_rows.append(f'<tr class="group-title-row"><td colspan="4"><strong>{group_name}</strong></td></tr>')

        rows = group.get("rows", [])
        if not rows:
            expense_rows.append('<tr><td colspan="4" class="empty">Нет строк, отмеченных в смету</td></tr>')

        for row in rows:
            title = escape(str(row["title"]))
            if row["is_subitem"]:
                title = f'<span class="sub">↳ {title}</span>'
            qty = "" if row["qty"] is None else escape(_fmt_money(row["qty"]).replace(",00", ""))
            unit_price = "" if row["unit_price"] is None else escape(_fmt_money(row["unit_price"]))
            row_sum = escape(_fmt_money(row["sum"]))
            expense_rows.append(
                f"""
                <tr>
                  <td>{title}</td>
                  <td class="center">{qty}</td>
                  <td class="num">{unit_price}</td>
                  <td class="num strong">{row_sum}</td>
                </tr>
                """
            )

        agency_amount = _safe_num(group.get("agency_amount"))
        if agency_amount > 0:
            expense_rows.append(
                f"""
                <tr class="sum-row agency-row">
                  <td><strong>Агентские ({agency_percent}%)</strong></td>
                  <td></td>
                  <td></td>
                  <td class="num strong">{escape(_fmt_money(agency_amount))}</td>
                </tr>
                """
            )

        expense_rows.append(
            f"""
            <tr class="sum-row">
              <td><strong>Итого</strong></td>
              <td></td>
              <td></td>
              <td class="num strong">{escape(_fmt_money(group.get("total_with_agency", 0.0)))}</td>
            </tr>
            """
        )
        if group_idx < len(expense_groups) - 1:
            expense_rows.append('<tr class="group-gap"><td colspan="4"></td></tr>')

    if common_agency_amount > 0:
        expense_rows.append(
            f"""
            <tr class="sum-row agency-row">
              <td><strong>Агентские ({agency_percent}%)</strong></td>
              <td></td>
              <td></td>
              <td class="num strong">{escape(_fmt_money(common_agency_amount))}</td>
            </tr>
            """
        )

    if not expense_rows:
        expense_rows.append('<tr><td colspan="4" class="empty">Нет строк, отмеченных в смету</td></tr>')

    project_title = escape(_fmt_plain(project["title"]))
    generated_at = escape(_fmt_generated_at(project.get("generated_at")))

    expenses_today = escape(_fmt_money(totals["expenses_today"]))
    expenses_before_usn = escape(_fmt_money(totals["expenses_before_usn"]))
    usn_rate_percent = escape(_fmt_money(totals["usn_rate_percent"]).replace(",00", ""))
    usn_amount = escape(_fmt_money(totals["usn_amount"]))
    expenses_with_usn = escape(_fmt_money(totals["expenses_with_usn"]))
    payments_upcoming = escape(_fmt_money(totals["payments_upcoming_total"]))
    project_price = escape(_fmt_money(project["project_price_total"]))

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Смета — {project_title}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700;800&family=Roboto+Mono:wght@400;500;700&display=swap');
    :root {{
      --bg:#f4f4f4; --text:#111111; --muted:#555555; --line:#cfcfcf; --head:#000000; --headText:#ffffff;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font:12.5px/1.25 "Roboto","Segoe UI",Arial,sans-serif; }}
    .page {{ max-width:1400px; margin:8px auto 12px; padding:0 10px; }}
    .top {{ margin-bottom:8px; }}
    .top-row {{
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:12px;
    }}
    .h1 {{ margin:0; font-size:24px; font-weight:800; letter-spacing:-0.01em; }}
    .generated-at {{ color:var(--muted); font-size:13px; font-weight:500; margin-top:4px; white-space:nowrap; }}
    .totals-strip {{
      display:grid;
      grid-template-columns:2.2fr 1fr;
      gap:8px;
      margin:36px 0 39px;
      align-items:start;
    }}
    .totals-strip-left {{
      display:grid;
      grid-template-columns:repeat(2,minmax(0,1fr));
      gap:8px;
      width:94%;
    }}
    .totals-strip-right {{
      display:block;
    }}
    .totals-strip-three {{
      grid-template-columns:repeat(3,minmax(0,1fr));
      margin-bottom:0;
    }}
    .total {{
      border:0;
      border-radius:0;
      padding:6px 8px;
      background:transparent;
      font-family:"Roboto","Segoe UI",Arial,sans-serif !important;
    }}
    .totals-strip .total {{ text-align:center; }}
    .total .k {{ color:var(--muted); font-size:11px; margin-bottom:2px; font-family:"Roboto","Segoe UI",Arial,sans-serif !important; }}
    .total .v {{ font-size:19px; font-weight:800; font-family:"Roboto","Segoe UI",Arial,sans-serif !important; }}
    .layout {{
      display:grid;
      grid-template-columns:2.2fr 1fr;
      gap:8px;
      align-items:start;
    }}
    .totals-layout {{
      display:grid;
      grid-template-columns:2.2fr 1fr;
      gap:8px;
      align-items:start;
      margin-top:0;
    }}
    .stack {{ display:grid; gap:8px; }}
    .panel {{ border:1px solid var(--line); border-radius:10px; background:#fff; overflow:hidden; }}
    .expenses-panel {{ width:94%; border-left:0; border-right:0; border-bottom:0; border-radius:0; }}
    .payments-panel {{ border-radius:0; }}
    .panel-h {{ background:var(--head); color:var(--headText); padding:7px 10px; font-size:13px; font-weight:700; font-family:"Roboto","Segoe UI",Arial,sans-serif; }}
    table {{ width:100%; border-collapse:collapse; table-layout:fixed; font-family:"Roboto Mono","Consolas","Menlo","Monaco",monospace; }}
    .expenses-table thead th:nth-child(1) {{ text-align:left; }}
    .expenses-table thead th:nth-child(2) {{ text-align:center; }}
    .expenses-table thead th:nth-child(3),
    .expenses-table thead th:nth-child(4) {{ text-align:right; }}
    th, td {{ border:1px solid var(--line); padding:5px 6px; vertical-align:middle; }}
    th {{ background:#f0f0f0; color:#202020; font-size:11px; font-weight:700; text-align:center; line-height:1.15; }}
    td {{ background:#fff; }}
    td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    td.center {{ text-align:center; }}
    td.strong {{ font-weight:700; }}
    .sub {{ color:#303030; }}
    .empty {{ text-align:center; color:var(--muted); padding:9px; }}
    .group-title-row td {{ background:#000; color:#fff; font-weight:700; border-top:0 !important; }}
    .sum-row td {{ background:#fafafa; border-bottom:1px solid var(--line) !important; }}
    .header-gap td {{
      border:0 !important;
      border-left:0 !important;
      border-right:0 !important;
      padding:0;
      height:21px;
      background:var(--bg);
      line-height:0;
    }}
    .group-gap td {{
      border:0 !important;
      padding:0;
      height:42px;
      background:var(--bg);
      line-height:0;
    }}
    .top, .totals-strip, .total {{
      font-family:"Roboto","Segoe UI",Arial,sans-serif;
    }}
    .totals-strip-three {{
      width:94%;
    }}
    @media (max-width:1100px) {{
      .layout {{ grid-template-columns:1fr; }}
      .totals-layout {{ grid-template-columns:1fr; }}
      .totals-strip {{ grid-template-columns:1fr; }}
      .totals-strip-left {{ width:100%; }}
      .expenses-panel,
      .totals-strip-three {{ width:100%; }}
    }}
    @media print {{
      @page {{ size: A4 landscape; margin: 8mm; }}
      body {{ background:#fff; }}
      .page {{ max-width:none; margin:0; padding:0; }}
      .h1 {{ font-size:18px; }}
      .totals-strip {{ gap:6px; margin-bottom:6px; }}
      .total {{ padding:4px 6px; }}
      .total .k {{ font-size:10px; }}
      .total .v {{ font-size:15px; }}
      .panel-h {{ font-size:12px; padding:6px 8px; }}
      th, td {{ padding:3px 4px; font-size:10.5px; }}
      .panel {{ break-inside:avoid; page-break-inside:avoid; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="top">
      <div class="top-row">
        <h1 class="h1">Смета проекта: {project_title}</h1>
        <div class="generated-at">Сформировано: {generated_at}</div>
      </div>
    </div>

    <div class="totals-strip">
      <div class="totals-strip-left">
        <div class="total"><div class="k">Стоимость проекта</div><div class="v">{project_price}</div></div>
        <div class="total"><div class="k">Расходы на сегодня</div><div class="v">{expenses_today}</div></div>
      </div>
      <div class="totals-strip-right">
        <div class="total"><div class="k">Предстоящие оплаты</div><div class="v">{payments_upcoming}</div></div>
      </div>
    </div>

    <div class="layout">
      <section class="panel expenses-panel">
        <div class="panel-h">Расходы</div>
        <table class="expenses-table">
          <thead>
            <tr>
              <th style="width:53%">Статья</th>
              <th style="width:9%">Шт</th>
              <th style="width:19%">Цена за ед</th>
              <th style="width:19%">Сумма</th>
            </tr>
          </thead>
          <tbody>
            <tr class="header-gap"><td colspan="4"></td></tr>
            {''.join(expense_rows)}
          </tbody>
        </table>
      </section>

      <section class="stack">
        <section class="panel payments-panel">
          <div class="panel-h">План по оплатам</div>
          <table>
            <thead>
              <tr>
                <th style="width:48%">Дата оплаты</th>
                <th style="width:32%">Сумма</th>
                <th style="width:20%">Статус</th>
              </tr>
            </thead>
            <tbody>
              {''.join(rows_payments)}
            </tbody>
          </table>
        </section>
      </section>
    </div>

    <div class="totals-layout">
      <div class="totals-strip totals-strip-three">
        <div class="total"><div class="k">Сумма (до УСН)</div><div class="v">{expenses_before_usn}</div></div>
        <div class="total"><div class="k">УСН ({usn_rate_percent}%)</div><div class="v">{usn_amount}</div></div>
        <div class="total"><div class="k">Сумма с УСН</div><div class="v">{expenses_with_usn}</div></div>
      </div>
      <div></div>
    </div>

  </div>
</body>
</html>"""


def _render_estimate2_html(payload: dict[str, Any]) -> str:
    project = payload["project"]
    expense_groups = payload.get("expense_groups", [])
    payments = payload["payments_plan"]
    totals = payload["totals"]

    rows_payments = []
    for row in payments:
        date = escape(_fmt_date_long(row["pay_date"]))
        amount = escape(_fmt_money_no_dec(row["amount"]))
        rows_payments.append(
            f"""
            <tr>
              <td class="center">{date}</td>
              <td class="num strong">{amount}</td>
            </tr>
            """
        )
    if not rows_payments:
        rows_payments.append('<tr><td colspan="2" class="empty">Нет оплат</td></tr>')

    agency_percent = escape(_fmt_money_no_dec(project.get("agency_fee_percent", 0)))
    common_agency_amount = _safe_num(totals.get("common_agency_amount"))
    expense_rows: list[str] = []
    for group_idx, group in enumerate(expense_groups):
        group_name = escape(_fmt_plain(group.get("group_name")))
        expense_rows.append(f'<tr class="group-title-row"><td colspan="5"><strong>{group_name}</strong></td></tr>')

        rows = group.get("rows", [])
        if not rows:
            expense_rows.append('<tr><td colspan="5" class="empty">Нет строк, отмеченных в смету</td></tr>')

        for row_idx, row in enumerate(rows, start=1):
            row_no = escape(f"{group_idx + 1}.{row_idx}")
            title = escape(str(row["title"]))
            if row["is_subitem"]:
                title = f'<span class="sub">↳ {title}</span>'
            qty = "" if row["qty"] is None else escape(_fmt_money_no_dec(row["qty"]))
            unit_price = "" if row["unit_price"] is None else escape(_fmt_money_no_dec(row["unit_price"]))
            row_sum = escape(_fmt_money_no_dec(row["sum"]))
            expense_rows.append(
                f"""
                <tr>
                  <td class="center">{row_no}</td>
                  <td>{title}</td>
                  <td class="center">{qty}</td>
                  <td class="num">{unit_price}</td>
                  <td class="num strong">{row_sum}</td>
                </tr>
                """
            )

        agency_amount = _safe_num(group.get("agency_amount"))
        if agency_amount > 0:
            expense_rows.append(
                f"""
                <tr class="sum-row agency-row">
                  <td></td>
                  <td><strong>Агентские ({agency_percent}%)</strong></td>
                  <td></td>
                  <td></td>
                  <td class="num strong">{escape(_fmt_money_no_dec(agency_amount))}</td>
                </tr>
                """
            )

        expense_rows.append(
            f"""
            <tr class="sum-row">
              <td></td>
              <td><strong>Итого</strong></td>
              <td></td>
              <td></td>
              <td class="num strong">{escape(_fmt_money_no_dec(group.get("total_with_agency", 0.0)))}</td>
            </tr>
            """
        )
        if group_idx < len(expense_groups) - 1:
            expense_rows.append('<tr class="group-gap"><td colspan="5"></td></tr>')

    if common_agency_amount > 0:
        expense_rows.append(
            f"""
            <tr class="sum-row agency-row">
              <td></td>
              <td><strong>Агентские ({agency_percent}%)</strong></td>
              <td></td>
              <td></td>
              <td class="num strong">{escape(_fmt_money_no_dec(common_agency_amount))}</td>
            </tr>
            """
        )

    if not expense_rows:
        expense_rows.append('<tr><td colspan="5" class="empty">Нет строк, отмеченных в смету</td></tr>')

    project_title = escape(_fmt_plain(project["title"]))
    generated_at = escape(_fmt_generated_at(project.get("generated_at")))

    expenses_today = escape(_fmt_money_no_dec(totals["expenses_today"]))
    expenses_before_usn = escape(_fmt_money_no_dec(totals["expenses_before_usn"]))
    usn_rate_percent = escape(_fmt_money_no_dec(totals["usn_rate_percent"]))
    usn_amount = escape(_fmt_money_no_dec(totals["usn_amount"]))
    expenses_with_usn = escape(_fmt_money_no_dec(totals["expenses_with_usn"]))
    project_price = escape(_fmt_money_no_dec(project["project_price_total"]))

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Смета 2 — {project_title}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700;800&family=Roboto+Mono:wght@400;500;700&display=swap');
    :root {{
      --bg:#f4f4f4; --text:#111111; --muted:#555555; --line:#cfcfcf; --head:#000000; --headText:#ffffff;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font:12.5px/1.25 "Roboto","Segoe UI",Arial,sans-serif; }}
    .page {{ max-width:780px; margin:8px auto 12px; padding:0 10px; }}
    .top-row {{
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:10px;
      margin-bottom:32px;
    }}
    .h1 {{ margin:0; font-size:24px; font-weight:800; letter-spacing:-0.01em; }}
    .generated-at {{ color:var(--muted); font-size:13px; font-weight:500; margin-top:4px; white-space:nowrap; }}
    .totals-strip {{
      display:grid;
      grid-template-columns:repeat(2,minmax(0,1fr));
      gap:8px;
      margin-bottom:30px;
    }}
    .total {{
      border:0;
      border-radius:0;
      padding:6px 8px;
      background:transparent;
      font-family:"Roboto","Segoe UI",Arial,sans-serif !important;
    }}
    .totals-strip .total {{ text-align:center; }}
    .total .k {{ color:var(--muted); font-size:11px; margin-bottom:2px; font-family:"Roboto","Segoe UI",Arial,sans-serif !important; }}
    .total .v {{ font-size:19px; font-weight:800; font-family:"Roboto","Segoe UI",Arial,sans-serif !important; }}
    .stack {{ display:grid; gap:10px; }}
    .panel {{ border:1px solid var(--line); border-radius:0; background:#fff; overflow:hidden; }}
    .expenses-panel {{ border-left:0; border-right:0; }}
    .panel-h {{ background:var(--head); color:var(--headText); padding:7px 10px; font-size:13px; font-weight:700; font-family:"Roboto","Segoe UI",Arial,sans-serif; }}
    table {{ width:100%; border-collapse:collapse; table-layout:fixed; font-family:"Roboto Mono","Consolas","Menlo","Monaco",monospace; }}
    .expenses-table thead th:nth-child(1) {{ text-align:center; }}
    .expenses-table thead th:nth-child(2) {{ text-align:left; }}
    .expenses-table thead th:nth-child(3) {{ text-align:center; }}
    .expenses-table thead th:nth-child(4),
    .expenses-table thead th:nth-child(5) {{ text-align:right; }}
    th, td {{ border:1px solid var(--line); padding:5px 6px; vertical-align:middle; }}
    th {{ background:#f0f0f0; color:#202020; font-size:11px; font-weight:700; text-align:center; line-height:1.15; }}
    td {{ background:#fff; }}
    td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    td.center {{ text-align:center; }}
    td.strong {{ font-weight:700; }}
    .sub {{ color:#303030; }}
    .empty {{ text-align:center; color:var(--muted); padding:9px; }}
    .group-title-row td {{ background:#000; color:#fff; font-weight:700; border-top:0 !important; }}
    .sum-row td {{ background:#fafafa; border-bottom:1px solid var(--line) !important; }}
    .header-gap td {{
      border:0 !important;
      border-left:0 !important;
      border-right:0 !important;
      padding:0;
      height:21px;
      background:var(--bg);
      line-height:0;
    }}
    .group-gap td {{
      border:0 !important;
      padding:0;
      height:42px;
      background:var(--bg);
      line-height:0;
    }}
    .sum-table th:nth-child(1), .sum-table td:nth-child(1),
    .sum-table th:nth-child(2), .sum-table td:nth-child(2),
    .sum-table th:nth-child(3), .sum-table td:nth-child(3) {{ text-align:right; }}
    .compact-panel {{ width:50%; margin-left:auto; margin-right:0; }}
    .sum-panel {{ margin-top:24px; }}
    .payments-panel {{ margin-top:24px; }}
    .payments-table {{ width:100%; margin:0; }}
    .payments-table th:nth-child(1), .payments-table td:nth-child(1) {{ text-align:center; }}
    .payments-table th:nth-child(2), .payments-table td:nth-child(2) {{ text-align:right; }}
    @media print {{
      @page {{ size: A4 portrait; margin: 8mm; }}
      body {{ background:#fff; }}
      .page {{ max-width:none; margin:0; padding:0; }}
      .h1 {{ font-size:16px; }}
      .generated-at {{ font-size:10px; }}
      .totals-strip {{ gap:6px; margin-bottom:24px; }}
      .total {{ padding:4px 6px; }}
      .total .k {{ font-size:9px; }}
      .total .v {{ font-size:14px; }}
      .panel-h {{ font-size:11px; padding:5px 7px; }}
      th, td {{ padding:3px 4px; font-size:10px; }}
      .panel {{ break-inside:avoid; page-break-inside:avoid; }}
      .group-gap td {{ height:16px; }}
      .compact-panel {{ width:50%; margin-left:auto; margin-right:0; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="top-row">
      <h1 class="h1">Проект: {project_title}</h1>
      <div class="generated-at">Сформировано: {generated_at}</div>
    </div>

    <div class="totals-strip">
      <div class="total"><div class="k">Стоимость проекта</div><div class="v">{project_price}</div></div>
      <div class="total"><div class="k">Расходы на сегодня</div><div class="v">{expenses_today}</div></div>
    </div>

    <div class="stack">
      <section class="panel expenses-panel">
        <div class="panel-h">Расходы</div>
        <table class="expenses-table">
          <thead>
            <tr>
              <th style="width:8%">№</th>
              <th style="width:45%">Статья</th>
              <th style="width:9%">Шт</th>
              <th style="width:19%">Цена за ед</th>
              <th style="width:19%">Сумма</th>
            </tr>
          </thead>
          <tbody>
            <tr class="header-gap"><td colspan="5"></td></tr>
            {''.join(expense_rows)}
          </tbody>
        </table>
      </section>

      <section class="panel compact-panel sum-panel">
        <div class="panel-h">Сумма</div>
        <table class="sum-table">
          <thead>
            <tr>
              <th style="width:31%">Сумма (до УСН)</th>
              <th style="width:31%">УСН ({usn_rate_percent}%)</th>
              <th style="width:38%">Сумма с УСН</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="num strong">{expenses_before_usn}</td>
              <td class="num strong">{usn_amount}</td>
              <td class="num strong">{expenses_with_usn}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="panel compact-panel payments-panel">
        <div class="panel-h">План по оплатам</div>
        <table class="payments-table">
          <thead>
            <tr>
              <th style="width:62%">Дата оплаты</th>
              <th style="width:38%">Сумма</th>
            </tr>
          </thead>
          <tbody>
            {''.join(rows_payments)}
          </tbody>
        </table>
      </section>
    </div>
  </div>
</body>
</html>"""


def _render_estimate2_pdf(payload: dict[str, Any]) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except Exception as exc:
        raise ValueError("PDF_LIBRARIES_NOT_INSTALLED") from exc

    font_regular = "Helvetica"
    font_bold = "Helvetica-Bold"
    font_table = "Courier"
    font_candidates = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for font_path in font_candidates:
        try:
            pdfmetrics.registerFont(TTFont("CXEMASans", font_path))
            pdfmetrics.registerFont(TTFont("CXEMASans-Bold", font_path))
            font_regular = "CXEMASans"
            font_bold = "CXEMASans-Bold"
            font_table = "CXEMASans"
            break
        except Exception:
            continue

    project = payload["project"]
    expense_groups = payload.get("expense_groups", [])
    payments = payload.get("payments_plan", [])
    totals = payload["totals"]

    line = colors.HexColor("#cfcfcf")
    bg_header = colors.black
    bg_muted = colors.HexColor("#f0f0f0")
    bg_sum = colors.HexColor("#fafafa")

    def row_h(base: float, k: float) -> float:
        return max(base * k, 7.0)

    n_payment_rows = max(1, len(payments))
    n_group_gaps = max(0, len(expense_groups) - 1)
    n_expense_rows = 0
    for g in expense_groups:
        n_expense_rows += 1
        n_expense_rows += len(g.get("rows") or [])
        if _safe_num(g.get("agency_amount")) > 0:
            n_expense_rows += 1
        n_expense_rows += 1
    if _safe_num(totals.get("common_agency_amount")) > 0:
        n_expense_rows += 1

    page_w, page_h = A4
    margin = 8 * mm
    content_h = page_h - 2 * margin

    expenses_table_h = 18 + 17 + 12 + (n_expense_rows * 16) + (n_group_gaps * 20)
    totals_block_h = 18 + 17 + 16
    payments_table_h = 18 + 17 + (n_payment_rows * 16)
    required_h = 18 + 10 + 30 + 8 + expenses_table_h + 8 + totals_block_h + 8 + payments_table_h
    k = min(1.0, content_h / max(required_h, 1))

    h_title = row_h(18, k)
    h_after_title = row_h(16, k)
    h_card = row_h(30, k)
    h_after_cards = row_h(24, k)
    h_panel_h = row_h(18, k)
    h_head = row_h(17, k)
    h_header_gap = row_h(12, k)
    h_row = row_h(16, k)
    h_group_gap = row_h(20, k)
    h_after_expenses = row_h(24, k)
    h_sum_panel_h = row_h(18, k)
    h_sum_head = row_h(17, k)
    h_after_totals = row_h(24, k)

    f_base = 10.0
    f_title = f_base + 1
    f_meta = f_base - 1
    f_tbl_h = f_base - 0.2
    f_tbl = f_base - 0.2
    f_top_label = f_base
    f_top_value = f_base + 2
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Смета 2 — {project.get('title', '')}")
    c.setFillColor(colors.white)
    c.rect(0, 0, page_w, page_h, stroke=0, fill=1)

    x0 = margin
    y_top = page_h - margin
    content_w = page_w - (2 * margin)
    gap = row_h(6, k)

    def rect_top(
        x: float,
        y: float,
        w: float,
        h: float,
        fill_color: Any = None,
        stroke_color: Any = line,
        stroke_width: float = 0.8,
    ) -> None:
        if fill_color is not None:
            c.setFillColor(fill_color)
        else:
            c.setFillColor(colors.white)
        c.setStrokeColor(stroke_color)
        c.setLineWidth(stroke_width)
        c.rect(x, y - h, w, h, stroke=1, fill=1)

    def draw_text_left(
        x: float,
        y: float,
        h: float,
        text: str,
        font_name: str,
        font_size: float,
        color: Any = colors.black,
        pad: float = 6.0,
    ) -> None:
        c.setFillColor(color)
        c.setFont(font_name, font_size)
        base = y - (h + font_size) / 2 + 2
        c.drawString(x + pad, base, text)

    def draw_text_center(
        x: float,
        y: float,
        w: float,
        h: float,
        text: str,
        font_name: str,
        font_size: float,
        color: Any = colors.black,
    ) -> None:
        c.setFillColor(color)
        c.setFont(font_name, font_size)
        base = y - (h + font_size) / 2 + 2
        tw = c.stringWidth(text, font_name, font_size)
        c.drawString(x + (w - tw) / 2, base, text)

    def draw_text_right(
        x: float,
        y: float,
        w: float,
        h: float,
        text: str,
        font_name: str,
        font_size: float,
        color: Any = colors.black,
        pad: float = 6.0,
    ) -> None:
        c.setFillColor(color)
        c.setFont(font_name, font_size)
        base = y - (h + font_size) / 2 + 2
        c.drawRightString(x + w - pad, base, text)

    project_title = _fmt_plain(project.get("title"))
    generated_at = _fmt_generated_at(project.get("generated_at"))
    c.setFillColor(colors.black)
    c.setFont(font_bold, f_title)
    c.drawString(x0, y_top - f_title, f"Проект: {project_title}")
    c.setFillColor(colors.HexColor("#555555"))
    c.setFont(font_regular, f_meta)
    c.drawRightString(x0 + content_w, y_top - f_meta, f"Сформировано: {generated_at}")
    y = y_top - h_title - h_after_title

    card_w = (content_w - gap) / 2.0
    kpi = [
        ("Стоимость проекта", _fmt_money_no_dec(project.get("project_price_total", 0.0))),
        ("Расходы на сегодня", _fmt_money_no_dec(totals.get("expenses_today", 0.0))),
    ]
    for i, (label, value) in enumerate(kpi):
        x = x0 + i * (card_w + gap)
        rect_top(x, y, card_w, h_card, fill_color=colors.white, stroke_color=line)
        c.setFillColor(colors.HexColor("#555555"))
        c.setFont(font_regular, f_top_label)
        label_w = c.stringWidth(label, font_regular, f_top_label)
        c.drawString(x + (card_w - label_w) / 2, y - f_top_label - 5, label)
        c.setFillColor(colors.black)
        c.setFont(font_bold, f_top_value)
        value_w = c.stringWidth(value, font_bold, f_top_value)
        c.drawString(x + (card_w - value_w) / 2, y - h_card + 6, value)
    y -= h_card + h_after_cards

    exp_x = x0
    exp_w = content_w
    exp_cols = [exp_w * 0.08, exp_w * 0.45, exp_w * 0.09, exp_w * 0.19, exp_w * 0.19]
    rect_top(exp_x, y, exp_w, h_panel_h, fill_color=bg_header, stroke_color=bg_header)
    draw_text_left(exp_x, y, h_panel_h, "Расходы", font_bold, f_tbl_h, colors.white, 8)
    y -= h_panel_h

    x = exp_x
    headers = ["№", "Статья", "Шт", "Цена за ед", "Сумма"]
    for i, w in enumerate(exp_cols):
        rect_top(x, y, w, h_head, fill_color=bg_muted, stroke_color=line)
        if i == 0:
            draw_text_center(x, y, w, h_head, headers[i], font_bold, f_tbl_h, colors.HexColor("#202020"))
        elif i == 1:
            draw_text_left(x, y, h_head, headers[i], font_bold, f_tbl_h, colors.HexColor("#202020"), 6)
        elif i == 2:
            draw_text_center(x, y, w, h_head, headers[i], font_bold, f_tbl_h, colors.HexColor("#202020"))
        else:
            draw_text_right(x, y, w, h_head, headers[i], font_bold, f_tbl_h, colors.HexColor("#202020"), 6)
        x += w
    y -= h_head + h_header_gap

    agency_percent = _fmt_money_no_dec(project.get("agency_fee_percent", 0))
    for idx, group in enumerate(expense_groups):
        rect_top(exp_x, y, exp_w, h_row, fill_color=bg_header, stroke_color=bg_header)
        draw_text_left(exp_x, y, h_row, _fmt_plain(group.get("group_name")), font_bold, f_tbl, colors.white, 6)
        y -= h_row

        for row_idx, row in enumerate(group.get("rows") or [], start=1):
            x = exp_x
            title = str(row.get("title") or "")
            if row.get("is_subitem"):
                title = f"↳ {title}"
            vals = [
                f"{idx + 1}.{row_idx}",
                title,
                "" if row.get("qty") is None else _fmt_money_no_dec(row.get("qty")),
                "" if row.get("unit_price") is None else _fmt_money_no_dec(row.get("unit_price")),
                _fmt_money_no_dec(row.get("sum")),
            ]
            for i, w in enumerate(exp_cols):
                rect_top(x, y, w, h_row, fill_color=colors.white, stroke_color=line)
                if i == 0:
                    draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
                elif i == 1:
                    draw_text_left(x, y, h_row, vals[i], font_table, f_tbl, colors.black, 6)
                elif i == 2:
                    draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
                else:
                    draw_text_right(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black, 6)
                x += w
            y -= h_row

        agency_amount = _safe_num(group.get("agency_amount"))
        if agency_amount > 0:
            x = exp_x
            vals = ["", f"Агентские ({agency_percent}%)", "", "", _fmt_money_no_dec(agency_amount)]
            for i, w in enumerate(exp_cols):
                rect_top(x, y, w, h_row, fill_color=bg_sum, stroke_color=line)
                if i == 0:
                    draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
                elif i == 1:
                    draw_text_left(x, y, h_row, vals[i], font_bold, f_tbl, colors.black, 6)
                elif i == 2:
                    draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
                else:
                    draw_text_right(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black, 6)
                x += w
            y -= h_row

        x = exp_x
        vals = ["", "Итого", "", "", _fmt_money_no_dec(group.get("total_with_agency", 0.0))]
        for i, w in enumerate(exp_cols):
            rect_top(x, y, w, h_row, fill_color=bg_sum, stroke_color=line)
            if i == 0:
                draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
            elif i == 1:
                draw_text_left(x, y, h_row, vals[i], font_bold, f_tbl, colors.black, 6)
            elif i == 2:
                draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
            else:
                draw_text_right(x, y, w, h_row, vals[i], font_bold if i == 4 else font_table, f_tbl, colors.black, 6)
            x += w
        y -= h_row

        if idx < len(expense_groups) - 1:
            y -= h_group_gap

    common_agency_amount = _safe_num(totals.get("common_agency_amount"))
    if common_agency_amount > 0:
        x = exp_x
        vals = ["", f"Агентские ({agency_percent}%)", "", "", _fmt_money_no_dec(common_agency_amount)]
        for i, w in enumerate(exp_cols):
            rect_top(x, y, w, h_row, fill_color=bg_sum, stroke_color=line)
            if i == 0:
                draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
            elif i == 1:
                draw_text_left(x, y, h_row, vals[i], font_bold, f_tbl, colors.black, 6)
            elif i == 2:
                draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
            else:
                draw_text_right(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black, 6)
            x += w
        y -= h_row

    y -= h_after_expenses

    sum_w = exp_w * 0.50
    sum_x = exp_x + (exp_w - sum_w)
    # Keep right "Сумма" column width equal to the main expenses table right column (19% of full table).
    # Compact blocks are 50% width, so right column share there should be 38% (0.5 * 0.38 = 0.19).
    sum_cols = [sum_w * 0.31, sum_w * 0.31, sum_w * 0.38]
    rect_top(sum_x, y, sum_w, h_sum_panel_h, fill_color=bg_header, stroke_color=bg_header)
    draw_text_left(sum_x, y, h_sum_panel_h, "Сумма", font_bold, f_tbl_h, colors.white, 8)
    y -= h_sum_panel_h

    x = sum_x
    sum_headers = [
        "Сумма (до УСН)",
        f"УСН ({_fmt_money_no_dec(totals.get('usn_rate_percent', 0.0))}%)",
        "Сумма с УСН",
    ]
    for i, w in enumerate(sum_cols):
        rect_top(x, y, w, h_sum_head, fill_color=bg_muted, stroke_color=line)
        if i == 0:
            draw_text_left(x, y, h_sum_head, sum_headers[i], font_bold, f_tbl_h, colors.HexColor("#202020"), 6)
        else:
            draw_text_right(x, y, w, h_sum_head, sum_headers[i], font_bold, f_tbl_h, colors.HexColor("#202020"), 6)
        x += w
    y -= h_sum_head

    sum_values = [
        _fmt_money_no_dec(totals.get("expenses_before_usn", 0.0)),
        _fmt_money_no_dec(totals.get("usn_amount", 0.0)),
        _fmt_money_no_dec(totals.get("expenses_with_usn", 0.0)),
    ]
    x = sum_x
    for i, w in enumerate(sum_cols):
        rect_top(x, y, w, h_row, fill_color=colors.white, stroke_color=line)
        draw_text_right(x, y, w, h_row, sum_values[i], font_bold, f_tbl, colors.black, 6)
        x += w
    y -= h_row

    y -= h_after_totals

    pay_w = exp_w * 0.50
    pay_x = exp_x + (exp_w - pay_w)
    # Same alignment rule: right "Сумма" column = 19% of full table width -> 38% of compact block.
    pay_cols = [pay_w * 0.62, pay_w * 0.38]
    rect_top(pay_x, y, pay_w, h_panel_h, fill_color=bg_header, stroke_color=bg_header)
    draw_text_left(pay_x, y, h_panel_h, "План по оплатам", font_bold, f_tbl_h, colors.white, 8)
    y -= h_panel_h

    x = pay_x
    pay_headers = ["Дата оплаты", "Сумма"]
    for i, w in enumerate(pay_cols):
        rect_top(x, y, w, h_head, fill_color=bg_muted, stroke_color=line)
        if i == 0:
            draw_text_center(x, y, w, h_head, pay_headers[i], font_bold, f_tbl_h, colors.HexColor("#202020"))
        else:
            draw_text_right(x, y, w, h_head, pay_headers[i], font_bold, f_tbl_h, colors.HexColor("#202020"), 6)
        x += w
    y -= h_head

    payment_rows = payments or [{"pay_date": None, "amount": ""}]
    for row in payment_rows:
        x = pay_x
        vals = [
            _fmt_date_long(row.get("pay_date")),
            _fmt_money_no_dec(row.get("amount")) if row.get("amount") not in {"", None} else "",
        ]
        for i, w in enumerate(pay_cols):
            rect_top(x, y, w, h_row, fill_color=colors.white, stroke_color=line)
            if i == 0:
                draw_text_center(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black)
            else:
                draw_text_right(x, y, w, h_row, vals[i], font_table, f_tbl, colors.black, 6)
            x += w
        y -= h_row

    c.save()
    return buf.getvalue()


def _render_pdf_from_html(html: str) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise ValueError("BROWSER_PDF_NOT_INSTALLED") from exc

    cache_key = hashlib.sha256(html.encode("utf-8")).hexdigest()
    cached = _pdf_cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        browser = _get_or_start_pdf_browser(sync_playwright)
        context = browser.new_context(locale="ru-RU")
        try:
            page = context.new_page()
            # "networkidle" is slow for pages with remote resources; DOM load is enough for our static layout.
            page.set_content(html, wait_until="domcontentloaded")
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
            )
        finally:
            context.close()
        _pdf_cache_put(cache_key, pdf_bytes)
        return pdf_bytes
    except Exception as exc:
        raise ValueError("BROWSER_PDF_RENDER_FAILED") from exc


def _get_or_start_pdf_browser(sync_playwright: Any) -> Any:
    global _PLAYWRIGHT, _PLAYWRIGHT_BROWSER
    with _PDF_BROWSER_LOCK:
        try:
            if _PLAYWRIGHT_BROWSER is not None and _PLAYWRIGHT_BROWSER.is_connected():
                return _PLAYWRIGHT_BROWSER
        except Exception:
            _PLAYWRIGHT_BROWSER = None

        if _PLAYWRIGHT is None:
            _PLAYWRIGHT = sync_playwright().start()
        _PLAYWRIGHT_BROWSER = _PLAYWRIGHT.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        return _PLAYWRIGHT_BROWSER


def _pdf_cache_get(key: str) -> Optional[bytes]:
    now = time.time()
    with _PDF_CACHE_LOCK:
        hit = _PDF_HTML_CACHE.get(key)
        if not hit:
            return None
        ts, payload = hit
        if now - ts > _PDF_CACHE_TTL_SECONDS:
            _PDF_HTML_CACHE.pop(key, None)
            return None
        return payload


def _pdf_cache_put(key: str, payload: bytes) -> None:
    now = time.time()
    with _PDF_CACHE_LOCK:
        _PDF_HTML_CACHE[key] = (now, payload)
        expired = [k for k, (ts, _) in _PDF_HTML_CACHE.items() if now - ts > _PDF_CACHE_TTL_SECONDS]
        for k in expired:
            _PDF_HTML_CACHE.pop(k, None)
        if len(_PDF_HTML_CACHE) <= _PDF_CACHE_MAX_ENTRIES:
            return
        # Remove oldest entries first.
        ordered = sorted(_PDF_HTML_CACHE.items(), key=lambda item: item[1][0])
        for k, _ in ordered[: len(_PDF_HTML_CACHE) - _PDF_CACHE_MAX_ENTRIES]:
            _PDF_HTML_CACHE.pop(k, None)


def _shutdown_pdf_renderer() -> None:
    global _PLAYWRIGHT, _PLAYWRIGHT_BROWSER
    with _PDF_BROWSER_LOCK:
        try:
            if _PLAYWRIGHT_BROWSER is not None:
                _PLAYWRIGHT_BROWSER.close()
        except Exception:
            pass
        try:
            if _PLAYWRIGHT is not None:
                _PLAYWRIGHT.stop()
        except Exception:
            pass
        _PLAYWRIGHT_BROWSER = None
        _PLAYWRIGHT = None


atexit.register(_shutdown_pdf_renderer)


@router.get("/{project_id}/estimate/data")
def estimate_data(
    project_id: int,
    group_agency_ids: Optional[str] = Query(default=None),
    common_agency: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return _estimate_payload(
        db,
        project_id,
        group_agency_ids=_parse_group_ids(group_agency_ids),
        common_agency_enabled=bool(common_agency),
    )


@router.get("/{project_id}/estimate2/data")
def estimate2_data(
    project_id: int,
    group_agency_ids: Optional[str] = Query(default=None),
    common_agency: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return _estimate_payload(
        db,
        project_id,
        group_agency_ids=_parse_group_ids(group_agency_ids),
        common_agency_enabled=bool(common_agency),
    )


@router.get("/{project_id}/estimate/page", response_class=HTMLResponse)
def estimate_page(
    project_id: int,
    group_agency_ids: Optional[str] = Query(default=None),
    common_agency: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    payload = _estimate_payload(
        db,
        project_id,
        group_agency_ids=_parse_group_ids(group_agency_ids),
        common_agency_enabled=bool(common_agency),
    )
    return HTMLResponse(content=_render_estimate_html(payload), media_type="text/html; charset=utf-8")


@router.get("/{project_id}/estimate2/page", response_class=HTMLResponse)
def estimate2_page(
    project_id: int,
    group_agency_ids: Optional[str] = Query(default=None),
    common_agency: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    payload = _estimate_payload(
        db,
        project_id,
        group_agency_ids=_parse_group_ids(group_agency_ids),
        common_agency_enabled=bool(common_agency),
    )
    return HTMLResponse(content=_render_estimate2_html(payload), media_type="text/html; charset=utf-8")


@router.get("/{project_id}/estimate2/pdf")
def estimate2_pdf(
    project_id: int,
    group_agency_ids: Optional[str] = Query(default=None),
    common_agency: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    project = _project_or_404(db, project_id)
    try:
        payload = _estimate_payload(
            db,
            project_id,
            group_agency_ids=_parse_group_ids(group_agency_ids),
            common_agency_enabled=bool(common_agency),
        )
        html = _render_estimate2_html(payload)
        pdf_bytes = _render_pdf_from_html(html)
        file_name = _estimate_pdf_file_name(project.title)
        headers = {
            "Content-Disposition": (
                f'attachment; filename="estimate.pdf"; filename*=UTF-8\'\'{quote(file_name)}'
            )
        }
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
    except HTTPException:
        raise
    except ValueError as exc:
        detail = str(exc)
        status = 400
        if detail in {"PDF_LIBRARIES_NOT_INSTALLED", "BROWSER_PDF_NOT_INSTALLED", "BROWSER_PDF_RENDER_FAILED"}:
            status = 500
        raise HTTPException(status_code=status, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{project_id}/estimate/drive-upload")
def upload_estimate_to_drive(
    project_id: int,
    group_agency_ids: Optional[str] = Query(default=None),
    common_agency: int = Query(default=0),
    db: Session = Depends(get_db),
):
    project = _project_or_404(db, project_id)
    try:
        payload = _estimate_payload(
            db=db,
            project_id=project_id,
            group_agency_ids=_parse_group_ids(group_agency_ids),
            common_agency_enabled=bool(common_agency),
        )
        pdf_bytes = _render_estimate_pdf(payload)

        creds = _load_google_credentials(required=True)
        _, _, _, build = _import_google_deps()

        drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        folder_id = _resolve_drive_folder_id(drive, project)

        file_name = _estimate_pdf_file_name(project.title)
        created = _upload_or_replace_pdf_in_drive(
            drive_api=drive,
            folder_id=folder_id,
            file_name=file_name,
            pdf_bytes=pdf_bytes,
        )
        return {
            "ok": True,
            "file_id": created.get("id"),
            "name": created.get("name"),
            "web_view_link": _drive_web_view_link(created),
            "web_content_link": created.get("webContentLink"),
            "folder_id": folder_id,
        }
    except HTTPException:
        raise
    except ValueError as exc:
        detail = str(exc)
        status = 400
        if detail in {"GOOGLE_AUTH_REQUIRED", "GOOGLE_TOKEN_INVALID", "GOOGLE_TOKEN_REFRESH_FAILED"}:
            status = 401
        if detail == "PDF_LIBRARIES_NOT_INSTALLED":
            status = 500
        raise HTTPException(status_code=status, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{project_id}/estimate2/drive-upload")
def upload_estimate2_to_drive(
    project_id: int,
    group_agency_ids: Optional[str] = Query(default=None),
    common_agency: int = Query(default=0),
    db: Session = Depends(get_db),
):
    project = _project_or_404(db, project_id)
    try:
        payload = _estimate_payload(
            db=db,
            project_id=project_id,
            group_agency_ids=_parse_group_ids(group_agency_ids),
            common_agency_enabled=bool(common_agency),
        )
        html = _render_estimate2_html(payload)
        pdf_bytes = _render_pdf_from_html(html)

        creds = _load_google_credentials(required=True)
        _, _, _, build = _import_google_deps()

        drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        folder_id = _resolve_drive_folder_id(drive, project)

        file_name = _estimate_pdf_file_name(project.title)
        created = _upload_or_replace_pdf_in_drive(
            drive_api=drive,
            folder_id=folder_id,
            file_name=file_name,
            pdf_bytes=pdf_bytes,
        )
        return {
            "ok": True,
            "file_id": created.get("id"),
            "name": created.get("name"),
            "web_view_link": _drive_web_view_link(created),
            "web_content_link": created.get("webContentLink"),
            "folder_id": folder_id,
        }
    except HTTPException:
        raise
    except ValueError as exc:
        detail = str(exc)
        status = 400
        if detail in {"GOOGLE_AUTH_REQUIRED", "GOOGLE_TOKEN_INVALID", "GOOGLE_TOKEN_REFRESH_FAILED"}:
            status = 401
        if detail in {"PDF_LIBRARIES_NOT_INSTALLED", "BROWSER_PDF_NOT_INSTALLED", "BROWSER_PDF_RENDER_FAILED"}:
            status = 500
        raise HTTPException(status_code=status, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
