from __future__ import annotations
import uuid
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_

from .models import Project, ExpenseGroup, ExpenseItem, ClientPaymentsPlan, ClientPaymentsFact

def gen_stable_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"

def compute_project_financials(db: Session, project_id: int) -> dict:
    # expenses_total = sum(total_cost_internal) where total_cost_internal = base_total + extra_profit_amount
    items = db.execute(select(ExpenseItem).where(ExpenseItem.project_id == project_id)).scalars().all()
    expenses_total = 0.0
    extra_profit_total = 0.0
    for it in items:
        base = it.base_total
        if it.mode.value == "QTY_PRICE" and it.qty is not None and it.unit_price_base is not None:
            qty = float(it.qty)
            unit = float(it.unit_price_base)
            base = unit if qty == 0 else qty * unit
        extra = float(it.extra_profit_amount) if it.extra_profit_enabled else 0.0
        expenses_total += base + extra
        extra_profit_total += extra

    project = db.get(Project, project_id)
    if not project:
        return {"project_id": project_id, "expenses_total": 0.0, "agency_fee": 0.0, "extra_profit_total": 0.0, "in_pocket": 0.0, "diff": 0.0}

    project_total = float(project.project_price_total or 0.0)
    agency_fee = project_total * (float(project.agency_fee_percent) / 100.0)
    in_pocket = agency_fee + extra_profit_total
    diff = project_total - expenses_total - in_pocket

    return {
        "project_id": project_id,
        "expenses_total": round(expenses_total, 2),
        "agency_fee": round(agency_fee, 2),
        "extra_profit_total": round(extra_profit_total, 2),
        "in_pocket": round(in_pocket, 2),
        "diff": round(diff, 2),
    }

def expense_breakdown_to_date(db: Session, project_id: int, at: date) -> tuple[float, float]:
    # "Потрачено" = базовые расходы. "Доп прибыль" считаем отдельно.
    items = db.execute(
        select(ExpenseItem).where(
            ExpenseItem.project_id == project_id,
            or_(ExpenseItem.planned_pay_date <= at, ExpenseItem.planned_pay_date.is_(None)),
        )
    ).scalars().all()

    spent_base = 0.0
    extra_profit = 0.0
    for it in items:
        base = float(it.base_total or 0.0)
        if it.mode.value == "QTY_PRICE" and it.qty is not None and it.unit_price_base is not None:
            qty = float(it.qty)
            unit = float(it.unit_price_base)
            base = unit if qty == 0 else qty * unit
        spent_base += base
        if it.extra_profit_enabled:
            extra_profit += float(it.extra_profit_amount or 0.0)

    return spent_base, extra_profit

def is_project_active(project: Project, at: date) -> bool:
    if project.created_at.date() > at:
        return False
    if project.closed_at is not None and at > project.closed_at:
        return False
    return True

def received_to_date(db: Session, project_id: int, at: date) -> float:
    q = select(func.coalesce(func.sum(ClientPaymentsFact.amount), 0.0)).where(
        ClientPaymentsFact.project_id == project_id,
        ClientPaymentsFact.pay_date <= at
    )
    return float(db.execute(q).scalar_one())

def planned_to_date(db: Session, project_id: int, at: date) -> float:
    q = select(func.coalesce(func.sum(ClientPaymentsPlan.amount), 0.0)).where(
        ClientPaymentsPlan.project_id == project_id,
        ClientPaymentsPlan.pay_date <= at
    )
    return float(db.execute(q).scalar_one())
