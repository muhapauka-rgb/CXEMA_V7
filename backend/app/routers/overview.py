from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from ..db import get_db
from ..models import Project, ExpenseItem, ClientPaymentsPlan, ClientPaymentsFact
from ..schemas import OverviewSnapshot, SnapshotTotals, SnapshotProject, OverviewMonthRange
from ..utils import is_project_active, received_to_date, planned_to_date, compute_project_financials

router = APIRouter(prefix="/api/overview", tags=["overview"])

def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"

@router.get("/month-range", response_model=OverviewMonthRange)
def month_range(db: Session = Depends(get_db)):
    item_min, item_max = db.execute(
        select(func.min(ExpenseItem.planned_pay_date), func.max(ExpenseItem.planned_pay_date))
    ).one()
    plan_min, plan_max = db.execute(
        select(func.min(ClientPaymentsPlan.pay_date), func.max(ClientPaymentsPlan.pay_date))
    ).one()
    fact_min, fact_max = db.execute(
        select(func.min(ClientPaymentsFact.pay_date), func.max(ClientPaymentsFact.pay_date))
    ).one()

    points = [d for d in [item_min, item_max, plan_min, plan_max, fact_min, fact_max] if d is not None]
    if not points:
        now = date.today()
        return OverviewMonthRange(min_month=_month_key(now), max_month=_month_key(now))

    min_point = min(points)
    max_point = max(points)
    return OverviewMonthRange(min_month=_month_key(min_point), max_month=_month_key(max_point))

@router.get("/snapshot", response_model=OverviewSnapshot)
def snapshot(at: date = Query(..., description="YYYY-MM-DD"), db: Session = Depends(get_db)):
    projects = db.execute(select(Project)).scalars().all()

    active = []
    for p in projects:
        if is_project_active(p, at):
            active.append(p)

    received_total = 0.0
    planned_total = 0.0
    expected_total = 0.0
    agency_fee_to_date = 0.0
    extra_profit_to_date = 0.0
    in_pocket_to_date = 0.0

    out_projects = []
    for p in active:
        r_fact = received_to_date(db, p.id, at)
        pl = planned_to_date(db, p.id, at)
        r = r_fact + pl
        expected = float(p.expected_from_client_total)

        comp = compute_project_financials(db, p.id)
        # MVP: extra_profit_to_date = вся доп прибыль проекта (без датировки)
        ep = float(comp["extra_profit_total"])
        agency = (float(p.agency_fee_percent) / 100.0) * r
        in_pocket = agency + ep

        received_total += r
        planned_total += pl
        expected_total += expected
        agency_fee_to_date += agency
        extra_profit_to_date += ep
        in_pocket_to_date += in_pocket

        out_projects.append(SnapshotProject(
            project_id=p.id,
            title=p.title,
            active=True,
            received_to_date=round(r,2),
            expected_total=round(expected,2),
            remaining=round(max(expected - r, 0.0),2),
            agency_fee_to_date=round(agency,2),
            extra_profit_to_date=round(ep,2),
            in_pocket_to_date=round(in_pocket,2),
        ))

    totals = SnapshotTotals(
        active_projects_count=len(active),
        received_total=round(received_total,2),
        planned_total=round(planned_total,2),
        expected_total=round(expected_total,2),
        agency_fee_to_date=round(agency_fee_to_date,2),
        extra_profit_to_date=round(extra_profit_to_date,2),
        in_pocket_to_date=round(in_pocket_to_date,2),
    )

    return OverviewSnapshot(
        meta={"at": str(at), "currency": "RUB"},
        totals=totals,
        projects=out_projects
    )

@router.get("/map")
def overview_map(at: date = Query(..., description="YYYY-MM-DD"), db: Session = Depends(get_db)):
    # MVP: отдаём простой mind-map JSON (узлы/дети) — фронт рисует как хочет
    snap = snapshot(at=at, db=db)  # reuse
    root = {
        "title": f"Мир проектов — {snap.meta['at']}",
        "children": [
            {"title":"Баланс", "children":[
                {"title": f"Получено: {snap.totals.received_total}"},
                {"title": f"План до даты: {snap.totals.planned_total}"},
                {"title": f"Ожидаем всего: {snap.totals.expected_total}"},
            ]},
            {"title":"В кармане", "children":[
                {"title": f"Агентские (to date): {snap.totals.agency_fee_to_date}"},
                {"title": f"Доп прибыль (MVP): {snap.totals.extra_profit_to_date}"},
                {"title": f"Итого: {snap.totals.in_pocket_to_date}"},
            ]},
            {"title":"Проекты (активные)", "children":[
                {"title": f"{p.title} | получено {p.received_to_date} | осталось {p.remaining} | in_pocket {p.in_pocket_to_date}"}
                for p in snap.projects
            ]},
        ]
    }
    return {"at": snap.meta["at"], "root": root}
