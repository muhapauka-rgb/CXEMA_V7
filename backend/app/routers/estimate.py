from __future__ import annotations

from datetime import datetime
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

    expense_rows: list[dict[str, Any]] = []
    group_totals: dict[int, float] = {int(g.id): 0.0 for g in groups}
    expenses_total = 0.0
    for it in items:
        if not bool(getattr(it, "include_in_estimate", True)):
            continue
        adj = adjustment_by_item_id.get(int(it.id))
        discount_enabled = bool(adj.discount_enabled) if adj else False
        discount_amount = _safe_num(adj.discount_amount) if discount_enabled else 0.0
        base = _item_base_total(it)
        extra = _safe_num(it.extra_profit_amount) if bool(it.extra_profit_enabled) else 0.0
        row_total = base + extra - discount_amount
        expenses_total += row_total
        group_totals[int(it.group_id)] = _safe_num(group_totals.get(int(it.group_id), 0.0)) + row_total

        parent_title = ""
        is_subitem = False
        if it.parent_item_id is not None:
            parent = item_by_id.get(int(it.parent_item_id))
            if parent:
                parent_title = parent.title
                is_subitem = True

        expense_rows.append(
            {
                "id": int(it.id),
                "group_id": int(it.group_id),
                "group": group_name_by_id.get(int(it.group_id), ""),
                "title": it.title,
                "parent_title": parent_title,
                "is_subitem": is_subitem,
                "date": _fmt_date(it.planned_pay_date),
                "qty": None if it.qty is None else _safe_num(it.qty),
                "unit_price": None if it.unit_price_base is None else _safe_num(it.unit_price_base),
                "base": base,
                "extra": extra,
                "discount": discount_amount,
                "row_total": row_total,
            }
        )

    payments_rows: list[dict[str, Any]] = []
    payments_total = 0.0
    for pay in plans:
        amount = _safe_num(pay.amount)
        payments_total += amount
        payments_rows.append(
            {
                "id": int(pay.id),
                "pay_date": _fmt_date(pay.pay_date),
                "amount": amount,
                "note": pay.note or "",
            }
        )

    agency_percent = _safe_num(project.agency_fee_percent)
    selected_group_agencies = group_agency_ids or set()
    group_summaries: list[dict[str, Any]] = []
    group_agency_total = 0.0
    for g in groups:
        gid = int(g.id)
        base_total = _safe_num(group_totals.get(gid, 0.0))
        agency_enabled = gid in selected_group_agencies
        agency_amount = _percent_amount(base_total, agency_percent) if agency_enabled else 0.0
        group_agency_total += agency_amount
        if base_total == 0 and not agency_enabled:
            continue
        group_summaries.append(
            {
                "group_id": gid,
                "group_name": g.name,
                "base_total": base_total,
                "agency_enabled": agency_enabled,
                "agency_amount": agency_amount,
                "total_with_agency": base_total + agency_amount,
            }
        )

    common_agency_amount = (
        _percent_amount(_safe_num(project.project_price_total), agency_percent)
        if common_agency_enabled
        else 0.0
    )
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
            "project_price_total": _safe_num(project.project_price_total),
            "generated_at": datetime.utcnow().isoformat(),
        },
        "expenses": expense_rows,
        "group_summary": group_summaries,
        "payments_plan": payments_rows,
        "totals": {
            "expenses_total": expenses_total,
            "group_agency_total": group_agency_total,
            "common_agency_amount": common_agency_amount,
            "expenses_before_usn": expenses_before_usn,
            "usn_rate_percent": usn_rate,
            "usn_amount": usn_amount,
            "expenses_with_usn": expenses_with_usn,
            "payments_plan_total": payments_total,
            "balance_before_usn": payments_total - expenses_before_usn,
            "balance_with_usn": payments_total - expenses_with_usn,
        },
    }


def _render_estimate_html(payload: dict[str, Any]) -> str:
    project = payload["project"]
    expenses = payload["expenses"]
    payments = payload["payments_plan"]
    group_summary = payload.get("group_summary", [])
    totals = payload["totals"]

    rows_expenses = []
    for row in expenses:
        title = escape(str(row["title"]))
        if row["is_subitem"]:
            title = f'<span class="sub">↳ {title}</span>'
        group = escape(_fmt_plain(row["group"]))
        date = escape(_fmt_plain(row["date"]))
        qty = "" if row["qty"] is None else escape(_fmt_money(row["qty"]).replace(",00", ""))
        unit_price = "" if row["unit_price"] is None else escape(_fmt_money(row["unit_price"]))
        base = escape(_fmt_money(row["base"]))
        extra = "" if _safe_num(row["extra"]) == 0 else escape(_fmt_money(row["extra"]))
        discount = "" if _safe_num(row["discount"]) == 0 else escape(_fmt_money(row["discount"]))
        row_total = escape(_fmt_money(row["row_total"]))
        rows_expenses.append(
            f"""
            <tr>
              <td>{group}</td>
              <td>{title}</td>
              <td class="center">{date}</td>
              <td class="num">{qty}</td>
              <td class="num">{unit_price}</td>
              <td class="num">{base}</td>
              <td class="num">{extra}</td>
              <td class="num">{discount}</td>
              <td class="num strong">{row_total}</td>
            </tr>
            """
        )

    if not rows_expenses:
        rows_expenses.append('<tr><td colspan="9" class="empty">Нет строк, отмеченных в смету</td></tr>')

    rows_payments = []
    for row in payments:
        date = escape(_fmt_plain(row["pay_date"]))
        amount = escape(_fmt_money(row["amount"]))
        note = escape(_fmt_plain(row["note"]))
        rows_payments.append(
            f"""
            <tr>
              <td class="center">{date}</td>
              <td class="num strong">{amount}</td>
              <td>{note}</td>
            </tr>
            """
        )
    if not rows_payments:
        rows_payments.append('<tr><td colspan="3" class="empty">Нет плановых поступлений</td></tr>')

    group_rows = []
    for row in group_summary:
        group_name = escape(_fmt_plain(row["group_name"]))
        base_total = escape(_fmt_money(row["base_total"]))
        agency = escape(_fmt_money(row["agency_amount"])) if _safe_num(row["agency_amount"]) != 0 else ""
        total_with_agency = escape(_fmt_money(row["total_with_agency"]))
        group_rows.append(
            f"""
            <tr>
              <td>{group_name}</td>
              <td class="num">{base_total}</td>
              <td class="num">{agency}</td>
              <td class="num strong">{total_with_agency}</td>
            </tr>
            """
        )
    if _safe_num(totals.get("common_agency_amount")) > 0:
        group_rows.append(
            f"""
            <tr>
              <td><strong>Общие агентские</strong></td>
              <td class="num">—</td>
              <td class="num">{escape(_fmt_money(totals["common_agency_amount"]))}</td>
              <td class="num strong">{escape(_fmt_money(totals["common_agency_amount"]))}</td>
            </tr>
            """
        )
    if not group_rows:
        group_rows.append('<tr><td colspan="4" class="empty">Агентские по группам не включены</td></tr>')

    project_title = escape(_fmt_plain(project["title"]))
    organization = escape(_fmt_plain(project["organization"]))
    email = escape(_fmt_plain(project["email"]))
    phone = escape(_fmt_plain(project["phone"]))
    generated = escape(_fmt_plain(project["generated_at"]).replace("T", " ")[:19])

    expenses_total = escape(_fmt_money(totals["expenses_total"]))
    expenses_before_usn = escape(_fmt_money(totals["expenses_before_usn"]))
    usn_rate_percent = escape(_fmt_money(totals["usn_rate_percent"]).replace(",00", ""))
    usn_amount = escape(_fmt_money(totals["usn_amount"]))
    expenses_with_usn = escape(_fmt_money(totals["expenses_with_usn"]))
    payments_total = escape(_fmt_money(totals["payments_plan_total"]))
    balance_before_usn = escape(_fmt_money(totals["balance_before_usn"]))
    balance_with_usn = escape(_fmt_money(totals["balance_with_usn"]))
    project_price = escape(_fmt_money(project["project_price_total"]))

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Смета — {project_title}</title>
  <style>
    :root {{
      --bg:#f7f8fb; --text:#172033; --muted:#5d687a; --line:#d6dce6; --head:#1f3f67; --headText:#fff;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font:12.5px/1.25 "Manrope","Segoe UI",Arial,sans-serif; }}
    .page {{ max-width:1400px; margin:8px auto 12px; padding:0 10px; }}
    .top {{ display:grid; grid-template-columns:1fr auto; align-items:end; gap:10px; margin-bottom:8px; }}
    .h1 {{ margin:0; font-size:24px; font-weight:800; letter-spacing:-0.01em; }}
    .meta {{ color:var(--muted); font-size:11px; }}
    .meta-line {{
      display:grid;
      grid-template-columns:repeat(4,minmax(0,1fr));
      gap:8px;
      margin:0 0 8px;
      color:var(--muted);
      font-size:11px;
    }}
    .meta-line strong {{ color:var(--text); font-weight:700; }}
    .totals-strip {{
      display:grid;
      grid-template-columns:repeat(4,minmax(0,1fr));
      gap:8px;
      margin:0 0 8px;
    }}
    .total {{
      border:1px solid var(--line);
      border-radius:8px;
      padding:6px 8px;
      background:#fff;
    }}
    .total .k {{ color:var(--muted); font-size:11px; margin-bottom:2px; }}
    .total .v {{ font-size:19px; font-weight:800; }}
    .layout {{
      display:grid;
      grid-template-columns:2.2fr 1fr;
      gap:8px;
      align-items:start;
    }}
    .stack {{ display:grid; gap:8px; }}
    .panel {{ border:1px solid var(--line); border-radius:10px; background:#fff; overflow:hidden; }}
    .panel-h {{ background:var(--head); color:var(--headText); padding:7px 10px; font-size:13px; font-weight:700; }}
    table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
    th, td {{ border:1px solid var(--line); padding:5px 6px; vertical-align:middle; }}
    th {{ background:#eef3f9; color:#33445f; font-size:11px; font-weight:700; text-align:center; line-height:1.15; }}
    td {{ background:#fff; }}
    td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    td.center {{ text-align:center; }}
    td.strong {{ font-weight:700; }}
    .sub {{ color:#293a56; }}
    .empty {{ text-align:center; color:var(--muted); padding:9px; }}
    .footer {{ color:var(--muted); font-size:10px; margin-top:6px; }}
    .actions {{ display:flex; gap:8px; margin-top:8px; }}
    .btn {{ border:1px solid var(--line); border-radius:7px; background:#fff; color:var(--text); padding:5px 8px; font:inherit; font-weight:600; cursor:pointer; }}
    @media (max-width:1100px) {{
      .layout {{ grid-template-columns:1fr; }}
      .meta-line, .totals-strip {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
    }}
    @media print {{
      @page {{ size: A4 landscape; margin: 8mm; }}
      body {{ background:#fff; }}
      .page {{ max-width:none; margin:0; padding:0; }}
      .actions {{ display:none; }}
      .h1 {{ font-size:18px; }}
      .meta {{ font-size:10px; }}
      .meta-line, .totals-strip {{ gap:6px; margin-bottom:6px; }}
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
      <div class="meta">Сформировано: {generated}</div>
    </div>

    <div class="meta-line">
      <div>Организация: <strong>{organization}</strong></div>
      <div>Email: <strong>{email}</strong></div>
      <div>Телефон: <strong>{phone}</strong></div>
      <div>Проект: <strong>#{project["id"]}</strong></div>
    </div>

    <div class="totals-strip">
      <div class="total"><div class="k">Стоимость проекта</div><div class="v">{project_price}</div></div>
      <div class="total"><div class="k">Расходы (строки)</div><div class="v">{expenses_total}</div></div>
      <div class="total"><div class="k">План по оплатам</div><div class="v">{payments_total}</div></div>
      <div class="total"><div class="k">Разница до УСН</div><div class="v">{balance_before_usn}</div></div>
    </div>

    <div class="layout">
      <section class="panel">
        <div class="panel-h">Расходы (в смету)</div>
        <table>
          <thead>
            <tr>
              <th style="width:13%">Группа</th>
              <th style="width:19%">Статья</th>
              <th style="width:11%">Дата</th>
              <th style="width:6%">Шт</th>
              <th style="width:11%">Цена за ед</th>
              <th style="width:10%">База</th>
              <th style="width:9%">Доп прибыль</th>
              <th style="width:8%">Скидка</th>
              <th style="width:13%">Итог строки</th>
            </tr>
          </thead>
          <tbody>
            {''.join(rows_expenses)}
          </tbody>
        </table>
      </section>

      <div class="stack">
        <section class="panel">
          <div class="panel-h">План по доходам</div>
          <table>
            <thead>
              <tr>
                <th style="width:28%">Дата оплаты</th>
                <th style="width:32%">Сумма</th>
                <th>Примечание</th>
              </tr>
            </thead>
            <tbody>
              {''.join(rows_payments)}
            </tbody>
          </table>
        </section>

        <section class="panel">
          <div class="panel-h">Свод по группам (с агентскими)</div>
          <table>
            <thead>
              <tr>
                <th>Группа</th>
                <th style="width:26%">Сумма группы</th>
                <th style="width:26%">Агентские</th>
                <th style="width:28%">Сумма с агентскими</th>
              </tr>
            </thead>
            <tbody>
              {''.join(group_rows)}
            </tbody>
          </table>
        </section>
      </div>
    </div>

    <div class="totals-strip" style="margin-top:8px">
      <div class="total"><div class="k">Сумма (до УСН)</div><div class="v">{expenses_before_usn}</div></div>
      <div class="total"><div class="k">УСН ({usn_rate_percent}%)</div><div class="v">{usn_amount}</div></div>
      <div class="total"><div class="k">Сумма с УСН</div><div class="v">{expenses_with_usn}</div></div>
      <div class="total"><div class="k">Разница с УСН</div><div class="v">{balance_with_usn}</div></div>
    </div>

    <div class="actions">
      <button class="btn" onclick="window.print()">Печать / PDF</button>
    </div>
    <div class="footer">Источник данных: CXEMA V7</div>
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
