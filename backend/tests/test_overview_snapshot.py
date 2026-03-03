from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.routers.overview import snapshot
from app.routers.projects import create_group, create_item, create_project
from app.schemas import GroupCreate, ItemCreate, ProjectCreate


def test_overview_uses_extra_profit_from_expense_rows(db: Session) -> None:
    project = create_project(
        ProjectCreate(
            title="audit-overview",
            project_price_total=10_000,
            agency_fee_percent=10,
        ),
        db=db,
    )
    group = create_group(project.id, GroupCreate(name="grp"), db=db)
    create_item(
        project.id,
        ItemCreate(
            group_id=group.id,
            title="parent",
            mode="SINGLE_TOTAL",
            base_total=1000,
            extra_profit_enabled=True,
            extra_profit_amount=500,
            planned_pay_date=date(2026, 3, 3),
        ),
        db=db,
    )

    snap = snapshot(at=date(2026, 3, 31), db=db)
    row = next(p for p in snap.projects if p.project_id == project.id)
    assert row.extra_profit_to_date == 500
    assert snap.totals.extra_profit_to_date == 500

