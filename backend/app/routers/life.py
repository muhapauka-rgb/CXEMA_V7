from __future__ import annotations

from datetime import date, timedelta
from typing import DefaultDict, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project
from ..schemas import LifePeriod, LifePreviousMonthOut, LifeProjectBreakdown
from ..utils import project_pocket_monthly_components

router = APIRouter(prefix="/api/life", tags=["life"])


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _month_end(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1) - timedelta(days=1)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _month_prev(key: str) -> str:
    y, m = [int(x) for x in key.split("-")]
    if m == 1:
        return f"{y - 1:04d}-12"
    return f"{y:04d}-{m - 1:02d}"


def _month_next(key: str) -> str:
    y, m = [int(x) for x in key.split("-")]
    if m == 12:
        return f"{y + 1:04d}-01"
    return f"{y:04d}-{m + 1:02d}"


def _month_key_to_start(key: str) -> date:
    parts = key.strip().split("-")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="month: expected YYYY-MM")
    try:
        year = int(parts[0])
        month_num = int(parts[1])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="month: expected YYYY-MM") from exc
    if year < 1900 or year > 2100 or month_num < 1 or month_num > 12:
        raise HTTPException(status_code=400, detail="month: out of range")
    return date(year, month_num, 1)


def _month_key_from_today_next() -> str:
    today = date.today()
    if today.month == 12:
        return f"{today.year + 1:04d}-01"
    return f"{today.year:04d}-{today.month + 1:02d}"


def _month_label_ru(key: str) -> str:
    month_start = _month_key_to_start(key)
    return month_start.strftime("%m.%Y")


def _life_for_month(
    db: Session,
    target_amount: float,
    selected_month: str,
) -> LifePreviousMonthOut:
    target_month_start = _month_key_to_start(selected_month)
    source_month_key = _month_prev(selected_month)
    source_month_end = _month_end(_month_key_to_start(source_month_key))
    today = date.today()
    as_of = source_month_end if source_month_end <= today else today

    projects = db.execute(select(Project)).scalars().all()
    project_by_id = {p.id: p for p in projects}

    # Monthly inflow to "карман" by project after expense-priority logic.
    inflow_by_month_project: DefaultDict[str, DefaultDict[int, float]] = defaultdict(lambda: defaultdict(float))
    for project in projects:
        monthly = project_pocket_monthly_components(db, project, as_of)
        for month_key, amount in monthly.items():
            in_pocket_amount = float(amount.get("in_pocket", 0.0))
            if in_pocket_amount <= 0:
                continue
            inflow_by_month_project[month_key][project.id] += in_pocket_amount

    all_months = sorted(inflow_by_month_project.keys())
    if not all_months:
        return LifePreviousMonthOut(
            period=LifePeriod(
                month_start=target_month_start,
                month_end=_month_end(target_month_start),
                label=_month_label_ru(selected_month),
            ),
            target_amount=round(target_amount, 2),
            life_covered=0.0,
            life_gap=round(target_amount, 2),
            savings_total=0.0,
            projects=[],
        )

    first_month = all_months[0]
    # Build contiguous source-month timeline up to selected source month.
    timeline = [first_month]
    while timeline[-1] < source_month_key:
        timeline.append(_month_next(timeline[-1]))

    # Savings buckets: source_month -> project_id -> remaining amount.
    savings: DefaultDict[str, DefaultDict[int, float]] = defaultdict(lambda: defaultdict(float))
    used_for_selected: DefaultDict[tuple[int, str], float] = defaultdict(float)
    covered_selected = 0.0
    selected_target_month = selected_month

    for source_month in timeline:
        for pid, amount in inflow_by_month_project.get(source_month, {}).items():
            if amount > 0:
                savings[source_month][pid] += amount

        target_month = _month_next(source_month)
        need = float(target_amount)

        # Current source month first.
        consume_order = [source_month] + [m for m in sorted(savings.keys(), reverse=True) if m != source_month and m < source_month]
        for month_bucket in consume_order:
            if need <= 0:
                break
            bucket = savings.get(month_bucket)
            if not bucket:
                continue
            for pid in sorted(list(bucket.keys())):
                if need <= 0:
                    break
                available = float(bucket.get(pid, 0.0))
                if available <= 0:
                    continue
                take = min(available, need)
                bucket[pid] = available - take
                if bucket[pid] <= 1e-9:
                    bucket.pop(pid, None)
                need -= take
                if target_month == selected_target_month:
                    used_for_selected[(pid, month_bucket)] += take
            if not bucket:
                savings.pop(month_bucket, None)

        if target_month == selected_target_month:
            covered_selected = target_amount - max(need, 0.0)
            break

    life_covered = round(max(covered_selected, 0.0), 2)
    life_gap = round(max(target_amount - life_covered, 0.0), 2)
    savings_total = round(sum(float(v) for by_project in savings.values() for v in by_project.values()), 2)

    breakdown: list[LifeProjectBreakdown] = []
    source_month_inflow = inflow_by_month_project.get(source_month_key, {})
    keys_for_breakdown: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for pid in sorted(source_month_inflow.keys()):
        key = (pid, source_month_key)
        keys_for_breakdown.append(key)
        seen.add(key)
    for (pid, source_month) in sorted(used_for_selected.keys(), key=lambda x: used_for_selected[x], reverse=True):
        key = (pid, source_month)
        if key in seen:
            continue
        keys_for_breakdown.append(key)
        seen.add(key)

    for (pid, source_month) in keys_for_breakdown:
        project = project_by_id.get(pid)
        if not project:
            continue
        used_amount = round(float(used_for_selected.get((pid, source_month), 0.0)), 2)
        month_inflow = round(float(inflow_by_month_project.get(source_month, {}).get(pid, 0.0)), 2)
        if source_month == source_month_key:
            received_for_row = month_inflow
            to_life = used_amount
            to_savings = round(max(month_inflow - used_amount, 0.0), 2)
        else:
            # Older month bucket used as a source for selected target month.
            received_for_row = used_amount
            to_life = used_amount
            to_savings = 0.0
        # If money came from older savings bucket, explicitly show month-source in title.
        source_suffix = ""
        if source_month != source_month_key:
            source_suffix = f" ({_month_label_ru(source_month)})"
        breakdown.append(
            LifeProjectBreakdown(
                project_id=int(project.id),
                title=f"{project.title}{source_suffix}",
                organization=project.client_name,
                received_last_month=received_for_row,
                to_life=to_life,
                to_savings=to_savings,
            )
        )

    return LifePreviousMonthOut(
        period=LifePeriod(
            month_start=target_month_start,
            month_end=_month_end(target_month_start),
            label=_month_label_ru(selected_month),
        ),
        target_amount=round(target_amount, 2),
        life_covered=life_covered,
        life_gap=life_gap,
        savings_total=savings_total,
        projects=breakdown,
    )


@router.get("/previous-month", response_model=LifePreviousMonthOut)
def previous_month_life(
    target_amount: float = Query(100000.0, ge=0),
    db: Session = Depends(get_db),
):
    today = date.today()
    current_key = _month_key(today)
    selected_month = _month_next(current_key)
    return _life_for_month(db=db, target_amount=float(target_amount), selected_month=selected_month)


@router.get("/month", response_model=LifePreviousMonthOut)
def month_life(
    target_amount: float = Query(100000.0, ge=0),
    month: Optional[str] = Query(default=None, description="YYYY-MM"),
    db: Session = Depends(get_db),
):
    selected_month = month or _month_key_from_today_next()
    return _life_for_month(db=db, target_amount=float(target_amount), selected_month=selected_month)
