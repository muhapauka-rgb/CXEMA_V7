from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project
from ..schemas import DiscountSummaryOut, DiscountEntryOut, DiscountCounterpartyOut
from ..utils import effective_project_expense_rows

router = APIRouter(prefix="/api/discounts", tags=["discounts"])


@router.get("/summary", response_model=DiscountSummaryOut)
def discount_summary(
    as_of: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
):
    if as_of is None:
        as_of = date.today()
    projects = db.execute(select(Project)).scalars().all()
    entries: list[DiscountEntryOut] = []
    by_org: defaultdict[str, float] = defaultdict(float)

    for project in projects:
        rows = effective_project_expense_rows(db, int(project.id))
        for row in rows:
            item = row["item"]
            item_date = row["planned_pay_date"]
            if item_date is not None and item_date > as_of:
                continue
            discount = float(row.get("discount_total", 0.0))
            if abs(discount) < 1e-9:
                continue
            org = (project.client_name or "—").strip() or "—"
            by_org[org] += discount
            entries.append(
                DiscountEntryOut(
                    project_id=int(project.id),
                    project_title=project.title,
                    organization=project.client_name,
                    item_id=int(item.id),
                    item_title=item.title,
                    item_date=item_date,
                    discount_amount=round(discount, 2),
                )
            )

    entries.sort(
        key=lambda x: (
            x.organization or "—",
            x.project_title,
            x.item_date.isoformat() if x.item_date else "",
            x.item_id,
        )
    )
    counterparties = [
        DiscountCounterpartyOut(organization=org, discount_total=round(total, 2))
        for org, total in sorted(by_org.items(), key=lambda x: x[0])
    ]
    total_discount = round(sum(float(e.discount_amount) for e in entries), 2)

    return DiscountSummaryOut(
        as_of=as_of,
        total_discount=total_discount,
        entries=entries,
        counterparties=counterparties,
    )
