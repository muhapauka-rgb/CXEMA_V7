from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ClientBillingAdjustment, ClientPaymentsPlan, ExpenseGroup, ExpenseItem, ItemMode, Project

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


def _project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    return project


def _estimate_payload(db: Session, project_id: int) -> dict[str, Any]:
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
        "payments_plan": payments_rows,
        "totals": {
            "expenses_total": expenses_total,
            "payments_plan_total": payments_total,
            "balance": payments_total - expenses_total,
        },
    }


def _render_estimate_html(payload: dict[str, Any]) -> str:
    project = payload["project"]
    expenses = payload["expenses"]
    payments = payload["payments_plan"]
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

    project_title = escape(_fmt_plain(project["title"]))
    organization = escape(_fmt_plain(project["organization"]))
    email = escape(_fmt_plain(project["email"]))
    phone = escape(_fmt_plain(project["phone"]))
    generated = escape(_fmt_plain(project["generated_at"]).replace("T", " ")[:19])

    expenses_total = escape(_fmt_money(totals["expenses_total"]))
    payments_total = escape(_fmt_money(totals["payments_plan_total"]))
    balance = escape(_fmt_money(totals["balance"]))
    project_price = escape(_fmt_money(project["project_price_total"]))

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Смета — {project_title}</title>
  <style>
    :root {{
      --bg:#f5f7fa; --text:#172033; --muted:#5d687a; --line:#d6dce6; --head:#1f3f67; --headText:#fff;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.35 "Manrope","Segoe UI",Arial,sans-serif; }}
    .page {{ max-width:1280px; margin:18px auto 30px; padding:0 18px; }}
    .top {{ display:grid; grid-template-columns:1fr auto; align-items:end; gap:12px; margin-bottom:14px; }}
    .h1 {{ margin:0; font-size:30px; font-weight:800; letter-spacing:-0.02em; }}
    .meta {{ color:var(--muted); font-size:13px; }}
    .cards {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:12px 0 14px; }}
    .card {{ border:1px solid var(--line); border-radius:12px; padding:10px 12px; background:#fff; }}
    .card .k {{ color:var(--muted); font-size:12px; margin-bottom:5px; }}
    .card .v {{ font-size:20px; font-weight:800; }}
    .panel {{ border:1px solid var(--line); border-radius:14px; background:#fff; overflow:hidden; margin-bottom:12px; }}
    .panel-h {{ background:var(--head); color:var(--headText); padding:10px 12px; font-size:16px; font-weight:700; }}
    table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
    th, td {{ border:1px solid var(--line); padding:8px 10px; vertical-align:middle; }}
    th {{ background:#eef3f9; color:#33445f; font-size:12px; font-weight:700; text-align:center; }}
    td {{ background:#fff; }}
    td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    td.center {{ text-align:center; }}
    td.strong {{ font-weight:700; }}
    .sub {{ color:#293a56; }}
    .empty {{ text-align:center; color:var(--muted); padding:12px; }}
    .footer {{ color:var(--muted); font-size:12px; margin-top:8px; }}
    .actions {{ display:flex; gap:8px; margin-top:12px; }}
    .btn {{ border:1px solid var(--line); border-radius:9px; background:#fff; color:var(--text); padding:7px 10px; font:inherit; font-weight:600; cursor:pointer; }}
    @media (max-width:980px) {{ .cards {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
    @media print {{
      body {{ background:#fff; }}
      .page {{ max-width:none; margin:0; padding:0; }}
      .actions {{ display:none; }}
      .panel, .card {{ break-inside:avoid; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="top">
      <h1 class="h1">Смета проекта: {project_title}</h1>
      <div class="meta">Сформировано: {generated}</div>
    </div>

    <div class="cards">
      <div class="card"><div class="k">Организация</div><div class="v">{organization}</div></div>
      <div class="card"><div class="k">Email</div><div class="v">{email}</div></div>
      <div class="card"><div class="k">Телефон</div><div class="v">{phone}</div></div>
      <div class="card"><div class="k">Стоимость проекта</div><div class="v">{project_price}</div></div>
    </div>

    <section class="panel">
      <div class="panel-h">Расходы (в смету)</div>
      <table>
        <thead>
          <tr>
            <th style="width:13%">Группа</th>
            <th style="width:22%">Статья</th>
            <th style="width:12%">Дата</th>
            <th style="width:8%">Шт</th>
            <th style="width:12%">Цена за ед</th>
            <th style="width:11%">База</th>
            <th style="width:8%">Доп прибыль</th>
            <th style="width:8%">Скидка</th>
            <th style="width:12%">Итог строки</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows_expenses)}
        </tbody>
      </table>
    </section>

    <section class="panel">
      <div class="panel-h">План по доходам</div>
      <table>
        <thead>
          <tr>
            <th style="width:18%">Дата оплаты</th>
            <th style="width:20%">Сумма</th>
            <th>Примечание</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows_payments)}
        </tbody>
      </table>
    </section>

    <div class="cards">
      <div class="card"><div class="k">Итого расходов (смета)</div><div class="v">{expenses_total}</div></div>
      <div class="card"><div class="k">Планируемые поступления</div><div class="v">{payments_total}</div></div>
      <div class="card"><div class="k">Разница (план - расходы)</div><div class="v">{balance}</div></div>
      <div class="card"><div class="k">Проект</div><div class="v">#{project["id"]}</div></div>
    </div>

    <div class="actions">
      <button class="btn" onclick="window.print()">Печать / PDF</button>
    </div>
    <div class="footer">Источник данных: CXEMA V7</div>
  </div>
</body>
</html>"""


@router.get("/{project_id}/estimate/data")
def estimate_data(project_id: int, db: Session = Depends(get_db)):
    return _estimate_payload(db, project_id)


@router.get("/{project_id}/estimate/page", response_class=HTMLResponse)
def estimate_page(project_id: int, db: Session = Depends(get_db)):
    payload = _estimate_payload(db, project_id)
    return HTMLResponse(content=_render_estimate_html(payload), media_type="text/html; charset=utf-8")

