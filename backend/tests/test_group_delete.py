from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ClientBillingAdjustment, ExpenseGroup, ExpenseItem
from app.routers.projects import create_group, create_item, create_project, delete_group_post
from app.schemas import GroupCreate, ItemCreate, ProjectCreate


def test_delete_empty_group(db: Session) -> None:
    project = create_project(ProjectCreate(title="audit-empty-group"), db=db)
    group = create_group(project.id, GroupCreate(name="empty"), db=db)

    out = delete_group_post(project.id, group.id, db=db)
    assert out["deleted"] is True

    remaining = db.execute(
        select(func.count()).select_from(ExpenseGroup).where(ExpenseGroup.id == group.id)
    ).scalar_one()
    assert remaining == 0


def test_delete_filled_group_cascades_items_and_adjustments(db: Session) -> None:
    project = create_project(ProjectCreate(title="audit-filled-group"), db=db)
    group = create_group(project.id, GroupCreate(name="filled"), db=db)
    item = create_item(
        project.id,
        ItemCreate(
            group_id=group.id,
            title="row",
            mode="QTY_PRICE",
            qty=2,
            unit_price_base=100,
            base_total=200,
            discount_enabled=True,
            discount_amount=10,
            planned_pay_date=date.today(),
        ),
        db=db,
    )

    out = delete_group_post(project.id, group.id, db=db)
    assert out["deleted"] is True

    remaining_groups = db.execute(
        select(func.count()).select_from(ExpenseGroup).where(ExpenseGroup.id == group.id)
    ).scalar_one()
    remaining_items = db.execute(
        select(func.count()).select_from(ExpenseItem).where(ExpenseItem.group_id == group.id)
    ).scalar_one()
    remaining_adj = db.execute(
        select(func.count()).select_from(ClientBillingAdjustment).where(
            ClientBillingAdjustment.expense_item_id == item.id
        )
    ).scalar_one()

    assert remaining_groups == 0
    assert remaining_items == 0
    assert remaining_adj == 0

