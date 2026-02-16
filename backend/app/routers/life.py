from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ClientPaymentsFact, Project
from ..schemas import LifePeriod, LifePreviousMonthOut, LifeProjectBreakdown

router = APIRouter(prefix="/api/life", tags=["life"])


def _previous_month_range(today: date) -> tuple[date, date]:
    current_month_start = date(today.year, today.month, 1)
    prev_month_end = current_month_start - timedelta(days=1)
    prev_month_start = date(prev_month_end.year, prev_month_end.month, 1)
    return prev_month_start, prev_month_end


@router.get("/previous-month", response_model=LifePreviousMonthOut)
def previous_month_life(
    target_amount: float = Query(100000.0, ge=0),
    db: Session = Depends(get_db),
):
    month_start, month_end = _previous_month_range(date.today())

    rows = db.execute(
        select(
            ClientPaymentsFact.project_id,
            func.coalesce(func.sum(ClientPaymentsFact.amount), 0.0).label("amount"),
        ).where(
            ClientPaymentsFact.pay_date >= month_start,
            ClientPaymentsFact.pay_date <= month_end,
        ).group_by(ClientPaymentsFact.project_id)
    ).all()

    project_ids = [int(r.project_id) for r in rows]
    projects = db.execute(
        select(Project).where(Project.id.in_(project_ids))
    ).scalars().all() if project_ids else []
    project_by_id = {p.id: p for p in projects}

    raw = []
    for row in rows:
        amount = float(row.amount or 0.0)
        if amount <= 0:
            continue
        p = project_by_id.get(int(row.project_id))
        if not p:
            continue
        raw.append({
            "project_id": p.id,
            "title": p.title,
            "organization": p.client_name,
            "received_last_month": round(amount, 2),
        })

    raw.sort(key=lambda x: x["received_last_month"], reverse=True)

    remaining_for_life = float(target_amount)
    out_projects: list[LifeProjectBreakdown] = []
    for row in raw:
        amount = float(row["received_last_month"])
        to_life = min(amount, max(remaining_for_life, 0.0))
        to_savings = max(amount - to_life, 0.0)
        remaining_for_life -= to_life

        out_projects.append(
            LifeProjectBreakdown(
                project_id=row["project_id"],
                title=row["title"],
                organization=row["organization"],
                received_last_month=round(amount, 2),
                to_life=round(to_life, 2),
                to_savings=round(to_savings, 2),
            )
        )

    life_covered = round(float(target_amount) - max(remaining_for_life, 0.0), 2)
    life_gap = round(max(remaining_for_life, 0.0), 2)
    savings_total = round(sum(p.to_savings for p in out_projects), 2)

    return LifePreviousMonthOut(
        period=LifePeriod(
            month_start=month_start,
            month_end=month_end,
            label=f"{month_start.strftime('%m.%Y')}",
        ),
        target_amount=round(float(target_amount), 2),
        life_covered=life_covered,
        life_gap=life_gap,
        savings_total=savings_total,
        projects=out_projects,
    )
