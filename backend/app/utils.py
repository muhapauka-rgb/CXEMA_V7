from __future__ import annotations
import uuid
from collections import defaultdict
from datetime import date, datetime
from typing import DefaultDict
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_

from .models import Project, ExpenseGroup, ExpenseItem, ClientPaymentsPlan, ClientPaymentsFact

def gen_stable_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"

def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"

def _item_base_total(item: ExpenseItem) -> float:
    base = float(item.base_total or 0.0)
    if item.mode.value == "QTY_PRICE" and item.qty is not None and item.unit_price_base is not None:
        qty = float(item.qty)
        unit = float(item.unit_price_base)
        base = unit if qty == 0 else qty * unit
    return base

def project_pocket_monthly_components(db: Session, project: Project, as_of: date) -> dict[str, dict[str, float]]:
    # Cash model:
    # payments -> wallet, expenses first, then agency/extra claims.
    events_pay: DefaultDict[date, float] = defaultdict(float)
    events_expense: DefaultDict[date, float] = defaultdict(float)
    events_agency_claim: DefaultDict[date, float] = defaultdict(float)
    events_extra_claim: DefaultDict[date, float] = defaultdict(float)

    payments_fact = db.execute(
        select(ClientPaymentsFact).where(
            ClientPaymentsFact.project_id == project.id,
            ClientPaymentsFact.pay_date <= as_of,
        )
    ).scalars().all()
    payments_plan_due = db.execute(
        select(ClientPaymentsPlan).where(
            ClientPaymentsPlan.project_id == project.id,
            ClientPaymentsPlan.pay_date <= as_of,
        )
    ).scalars().all()

    agency_rate = float(project.agency_fee_percent or 0.0) / 100.0
    project_created = project.created_at.date()

    for rec in payments_fact:
        pay_date = rec.pay_date
        amount = float(rec.amount or 0.0)
        if amount <= 0:
            continue
        events_pay[pay_date] += amount
        events_agency_claim[pay_date] += amount * agency_rate

    for rec in payments_plan_due:
        pay_date = rec.pay_date
        amount = float(rec.amount or 0.0)
        if amount <= 0:
            continue
        events_pay[pay_date] += amount
        events_agency_claim[pay_date] += amount * agency_rate

    items = db.execute(
        select(ExpenseItem).where(ExpenseItem.project_id == project.id)
    ).scalars().all()
    for item in items:
        due_date = item.planned_pay_date or project_created
        if due_date > as_of:
            continue
        base = _item_base_total(item)
        if base > 0:
            events_expense[due_date] += base
        if item.extra_profit_enabled:
            extra = float(item.extra_profit_amount or 0.0)
            if extra > 0:
                events_extra_claim[due_date] += extra

    all_dates = sorted(
        set(events_pay.keys())
        | set(events_expense.keys())
        | set(events_agency_claim.keys())
        | set(events_extra_claim.keys())
    )
    if not all_dates:
        return {}

    wallet = 0.0
    pending_expense = 0.0
    pending_agency = 0.0
    pending_extra = 0.0
    out: DefaultDict[str, dict[str, float]] = defaultdict(lambda: {"agency": 0.0, "extra": 0.0, "in_pocket": 0.0})

    for d in all_dates:
        wallet += events_pay[d]
        pending_expense += events_expense[d]
        pending_agency += events_agency_claim[d]
        pending_extra += events_extra_claim[d]

        paid_expense = min(wallet, pending_expense)
        wallet -= paid_expense
        pending_expense -= paid_expense

        paid_agency = min(wallet, pending_agency)
        wallet -= paid_agency
        pending_agency -= paid_agency

        paid_extra = min(wallet, pending_extra)
        wallet -= paid_extra
        pending_extra -= paid_extra

        if paid_agency > 0 or paid_extra > 0:
            key = _month_key(d)
            out[key]["agency"] += paid_agency
            out[key]["extra"] += paid_extra
            out[key]["in_pocket"] += paid_agency + paid_extra

    return dict(out)

def compute_project_financials(db: Session, project_id: int) -> dict:
    # expenses_total = sum(total_cost_internal) where total_cost_internal = base_total + extra_profit_amount
    items = db.execute(select(ExpenseItem).where(ExpenseItem.project_id == project_id)).scalars().all()
    expenses_total = 0.0
    extra_profit_total = 0.0
    for it in items:
        base = _item_base_total(it)
        extra = float(it.extra_profit_amount) if it.extra_profit_enabled else 0.0
        expenses_total += base + extra
        extra_profit_total += extra

    project = db.get(Project, project_id)
    if not project:
        return {"project_id": project_id, "expenses_total": 0.0, "agency_fee": 0.0, "extra_profit_total": 0.0, "in_pocket": 0.0, "diff": 0.0}

    project_total = float(project.project_price_total or 0.0)
    agency_fee = project_total * (float(project.agency_fee_percent) / 100.0)
    in_pocket = agency_fee + extra_profit_total
    diff = project_total - expenses_total

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
    q_fact = select(func.coalesce(func.sum(ClientPaymentsFact.amount), 0.0)).where(
        ClientPaymentsFact.project_id == project_id,
        ClientPaymentsFact.pay_date <= at
    )
    q_plan_to_date = select(func.coalesce(func.sum(ClientPaymentsPlan.amount), 0.0)).where(
        ClientPaymentsPlan.project_id == project_id,
        ClientPaymentsPlan.pay_date <= at,
    )
    fact_sum = float(db.execute(q_fact).scalar_one())
    plan_sum = float(db.execute(q_plan_to_date).scalar_one())
    return fact_sum + plan_sum

def planned_to_date(db: Session, project_id: int, at: date) -> float:
    # Remaining planned inflow strictly after selected date.
    q = select(func.coalesce(func.sum(ClientPaymentsPlan.amount), 0.0)).where(
        ClientPaymentsPlan.project_id == project_id,
        ClientPaymentsPlan.pay_date > at,
    )
    return float(db.execute(q).scalar_one())
