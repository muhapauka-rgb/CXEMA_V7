from __future__ import annotations

from collections import defaultdict
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


def _month_label_ru_long(key: str) -> str:
    month_start = _month_key_to_start(key)
    month_names = [
        "январь",
        "февраль",
        "март",
        "апрель",
        "май",
        "июнь",
        "июль",
        "август",
        "сентябрь",
        "октябрь",
        "ноябрь",
        "декабрь",
    ]
    return f"{month_names[month_start.month - 1]} {month_start.year}"


def _life_for_month(
    db: Session,
    target_amount: float,
    selected_month: str,
) -> LifePreviousMonthOut:
    def _copy_savings_state(
        source: DefaultDict[str, DefaultDict[int, float]],
    ) -> dict[str, dict[int, float]]:
        snapshot: dict[str, dict[int, float]] = {}
        for month_key, by_project in source.items():
            month_snapshot = {int(pid): float(value) for pid, value in by_project.items() if float(value) > 0}
            if month_snapshot:
                snapshot[month_key] = month_snapshot
        return snapshot

    target_month_start = _month_key_to_start(selected_month)
    source_month_key = _month_prev(selected_month)
    source_month_end = _month_end(_month_key_to_start(source_month_key))
    # For life planning in future months, use full source month horizon
    # (planned payments/expenses inside that month must be considered).
    as_of = source_month_end

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
            reserve_used=0.0,
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
    reserve_used = 0.0
    selected_target_month = selected_month
    savings_before_selected: dict[str, dict[int, float]] = {}
    savings_after_selected: dict[str, dict[int, float]] = {}

    for source_month in timeline:
        for pid, amount in inflow_by_month_project.get(source_month, {}).items():
            if amount > 0:
                savings[source_month][pid] += amount

        target_month = _month_next(source_month)
        need = float(target_amount)
        is_selected_target = target_month == selected_target_month
        if is_selected_target:
            savings_before_selected = _copy_savings_state(savings)

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
                if is_selected_target:
                    used_for_selected[(pid, month_bucket)] += take
            if not bucket:
                savings.pop(month_bucket, None)

        if is_selected_target:
            covered_selected = target_amount - max(need, 0.0)
            reserve_used = sum(
                float(v)
                for (pid, month_bucket), v in used_for_selected.items()
                if month_bucket != source_month_key
            )
            savings_after_selected = _copy_savings_state(savings)
            break

    life_covered = round(max(covered_selected, 0.0), 2)
    life_gap = round(max(target_amount - life_covered, 0.0), 2)
    reserve_used = round(max(reserve_used, 0.0), 2)
    savings_total = round(sum(float(v) for by_project in savings.values() for v in by_project.values()), 2)

    breakdown: list[LifeProjectBreakdown] = []
    keys_for_breakdown: set[tuple[int, str]] = set()
    for pid in inflow_by_month_project.get(source_month_key, {}).keys():
        keys_for_breakdown.add((int(pid), source_month_key))
    for month_bucket, by_project in savings_before_selected.items():
        for pid in by_project.keys():
            keys_for_breakdown.add((int(pid), month_bucket))
    for key in used_for_selected.keys():
        keys_for_breakdown.add((int(key[0]), key[1]))

    def _month_order_num(key: str) -> int:
        y, m = [int(x) for x in key.split("-")]
        return y * 100 + m

    def _row_sort_key(key: tuple[int, str]) -> tuple[int, int, str]:
        pid, source_month = key
        project = project_by_id.get(pid)
        title = project.title if project else ""
        if source_month == source_month_key:
            return (0, 0, title)
        # Reserve rows: nearest month first, then title.
        return (1, -_month_order_num(source_month), title)

    for (pid, source_month) in sorted(keys_for_breakdown, key=_row_sort_key):
        project = project_by_id.get(pid)
        if not project:
            continue
        opening_balance = round(float(savings_before_selected.get(source_month, {}).get(pid, 0.0)), 2)
        used_amount = round(float(used_for_selected.get((pid, source_month), 0.0)), 2)
        closing_balance = round(float(savings_after_selected.get(source_month, {}).get(pid, 0.0)), 2)
        inflow_in_source_month = round(float(inflow_by_month_project.get(source_month, {}).get(pid, 0.0)), 2)
        if opening_balance <= 0 and used_amount <= 0 and closing_balance <= 0 and inflow_in_source_month <= 0:
            continue
        source_kind = "current" if source_month == source_month_key else "reserve"
        breakdown.append(
            LifeProjectBreakdown(
                project_id=int(project.id),
                title=project.title,
                organization=project.client_name,
                source_month_key=source_month,
                source_month_label=_month_label_ru_long(source_month),
                source_kind=source_kind,
                opening_balance=opening_balance,
                inflow_in_source_month=inflow_in_source_month,
                used_for_life=used_amount,
                closing_balance=closing_balance,
                received_last_month=inflow_in_source_month,
                to_life=used_amount,
                to_savings=closing_balance,
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
        reserve_used=reserve_used,
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
