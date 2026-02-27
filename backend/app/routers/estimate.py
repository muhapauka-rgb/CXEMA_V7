from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import Any, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ClientBillingAdjustment, ClientPaymentsPlan, ExpenseGroup, ExpenseItem, ItemMode, Project
from ..utils import get_global_usn_settings

router = APIRouter(prefix="/api/projects", tags=["estimate"])


def _safe_num(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _fmt_money(value: float) -> str:
    return f"{float(value or 0.0):,.2f}".replace(",", " ").replace(".", ",")


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


def _project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    return project


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
    .h1 {{ margin:0; font-size:24px; font-weight:800; letter-spacing:-0.01em; }}
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
      border:1px solid var(--line);
      border-radius:8px;
      padding:6px 8px;
      background:#fff;
      font-family:"Roboto","Segoe UI",Arial,sans-serif !important;
    }}
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
      <h1 class="h1">Смета проекта: {project_title}</h1>
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
