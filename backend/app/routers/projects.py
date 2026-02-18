from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, text

from ..db import get_db, engine, Base
from ..models import (
    Project,
    ExpenseGroup,
    ExpenseItem,
    ClientBillingAdjustment,
    ClientPaymentsPlan,
    ClientPaymentsFact,
    ItemMode,
    AdjustmentType,
)
from ..schemas import (
    ProjectCreate,
    ProjectUpdate,
    ProjectOut,
    GroupCreate,
    GroupUpdate,
    GroupOut,
    ItemCreate,
    ItemUpdate,
    ItemOut,
    BillingAdjustmentUpsert,
    BillingAdjustmentOut,
    PaymentPlanCreate,
    PaymentPlanUpdate,
    PaymentPlanOut,
    PaymentFactCreate,
    PaymentFactUpdate,
    PaymentFactOut,
    ProjectComputed,
)
from ..utils import compute_project_financials, gen_stable_id

router = APIRouter(prefix="/api/projects", tags=["projects"])

# MVP: create tables automatically on first import (без alembic пока)
Base.metadata.create_all(bind=engine)


def _ensure_sqlite_columns() -> None:
    if engine.dialect.name != "sqlite":
        return
    # Lightweight compatibility migration for existing SQLite files.
    with engine.begin() as conn:
        project_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(projects)"))}
        if "client_email" not in project_columns:
            conn.execute(text("ALTER TABLE projects ADD COLUMN client_email VARCHAR(255)"))
        if "client_phone" not in project_columns:
            conn.execute(text("ALTER TABLE projects ADD COLUMN client_phone VARCHAR(64)"))
        if "google_drive_url" not in project_columns:
            conn.execute(text("ALTER TABLE projects ADD COLUMN google_drive_url VARCHAR(1024)"))
        if "google_drive_folder" not in project_columns:
            conn.execute(text("ALTER TABLE projects ADD COLUMN google_drive_folder VARCHAR(255)"))
        if "agency_fee_percent" not in project_columns:
            conn.execute(text("ALTER TABLE projects ADD COLUMN agency_fee_percent FLOAT NOT NULL DEFAULT 10.0"))
        if "agency_fee_include_in_estimate" not in project_columns:
            conn.execute(text("ALTER TABLE projects ADD COLUMN agency_fee_include_in_estimate BOOLEAN NOT NULL DEFAULT 1"))

        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(expense_items)"))}
        if "include_in_estimate" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE expense_items "
                    "ADD COLUMN include_in_estimate BOOLEAN NOT NULL DEFAULT 1"
                )
            )
        if "parent_item_id" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE expense_items "
                    "ADD COLUMN parent_item_id INTEGER"
                )
            )
        adjustment_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(client_billing_adjustments)"))}
        if "discount_enabled" not in adjustment_columns:
            conn.execute(
                text(
                    "ALTER TABLE client_billing_adjustments "
                    "ADD COLUMN discount_enabled BOOLEAN NOT NULL DEFAULT 0"
                )
            )
        if "discount_amount" not in adjustment_columns:
            conn.execute(
                text(
                    "ALTER TABLE client_billing_adjustments "
                    "ADD COLUMN discount_amount FLOAT NOT NULL DEFAULT 0.0"
                )
            )


_ensure_sqlite_columns()

def _get_project_or_404(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "PROJECT_NOT_FOUND")
    return p

def _get_group_or_404(db: Session, project_id: int, group_id: int) -> ExpenseGroup:
    g = db.get(ExpenseGroup, group_id)
    if not g or g.project_id != project_id:
        raise HTTPException(404, "GROUP_NOT_FOUND")
    return g

def _get_item_or_404(db: Session, project_id: int, item_id: int) -> ExpenseItem:
    it = db.get(ExpenseItem, item_id)
    if not it or it.project_id != project_id:
        raise HTTPException(404, "ITEM_NOT_FOUND")
    return it

def _parse_mode(mode_raw: str) -> ItemMode:
    try:
        return ItemMode(mode_raw)
    except ValueError as exc:
        raise HTTPException(422, "ITEM_MODE_INVALID") from exc

def _parse_adjustment_type(value: str) -> AdjustmentType:
    try:
        return AdjustmentType(value)
    except ValueError as exc:
        raise HTTPException(422, "ADJUSTMENT_TYPE_INVALID") from exc

def _refresh_item_calculated_base(item: ExpenseItem) -> None:
    if item.mode == ItemMode.QTY_PRICE:
        if item.qty is None or item.unit_price_base is None:
            raise HTTPException(422, "QTY_PRICE_REQUIRES_QTY_AND_UNIT_PRICE")
        qty = float(item.qty)
        unit = float(item.unit_price_base)
        item.base_total = unit if qty == 0 else qty * unit


def _validate_parent_item(
    db: Session,
    project_id: int,
    group_id: int,
    parent_item_id: int | None,
    current_item_id: int | None = None,
) -> None:
    if parent_item_id is None:
        return
    if current_item_id is not None and parent_item_id == current_item_id:
        raise HTTPException(422, "PARENT_ITEM_SELF_REF")
    parent = db.get(ExpenseItem, parent_item_id)
    if not parent or parent.project_id != project_id:
        raise HTTPException(422, "PARENT_ITEM_NOT_FOUND")
    if parent.group_id != group_id:
        raise HTTPException(422, "PARENT_ITEM_GROUP_MISMATCH")
    # One nesting level: only top-level rows can be parents.
    if parent.parent_item_id is not None:
        raise HTTPException(422, "PARENT_ITEM_MUST_BE_TOP_LEVEL")
    if current_item_id is not None:
        has_children = db.execute(
            select(ExpenseItem.id).where(ExpenseItem.parent_item_id == current_item_id).limit(1)
        ).first() is not None
        if has_children:
            raise HTTPException(422, "ITEM_WITH_SUBITEMS_CANNOT_BE_SUBITEM")


def _load_discount_adjustment_for_item(db: Session, item_id: int) -> ClientBillingAdjustment | None:
    return db.execute(
        select(ClientBillingAdjustment).where(ClientBillingAdjustment.expense_item_id == item_id)
    ).scalar_one_or_none()


def _apply_item_discount(
    db: Session,
    item_id: int,
    discount_enabled: bool,
    discount_amount: float,
) -> None:
    adj = _load_discount_adjustment_for_item(db, item_id)
    if not adj:
        adj = ClientBillingAdjustment(
            expense_item_id=item_id,
            unit_price_full=0.0,
            unit_price_billable=0.0,
            adjustment_type=AdjustmentType.DISCOUNT,
            reason="",
        )
        db.add(adj)
    adj.discount_enabled = bool(discount_enabled)
    adj.discount_amount = float(discount_amount or 0.0)


def _attach_item_discounts(db: Session, project_id: int, items: list[ExpenseItem]) -> list[ExpenseItem]:
    if not items:
        return items
    adjustments = db.execute(
        select(ClientBillingAdjustment).join(ExpenseItem, ExpenseItem.id == ClientBillingAdjustment.expense_item_id).where(
            ExpenseItem.project_id == project_id
        )
    ).scalars().all()
    by_item_id = {int(adj.expense_item_id): adj for adj in adjustments}
    for it in items:
        adj = by_item_id.get(int(it.id))
        setattr(it, "discount_enabled", bool(adj.discount_enabled) if adj else False)
        setattr(it, "discount_amount", float(adj.discount_amount or 0.0) if adj else 0.0)
    return items

@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.execute(select(Project).order_by(Project.id.desc())).scalars().all()

@router.post("", response_model=ProjectOut)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    p = Project(
        title=payload.title,
        client_name=payload.client_name,
        client_email=payload.client_email,
        client_phone=payload.client_phone,
        google_drive_url=payload.google_drive_url,
        google_drive_folder=payload.google_drive_folder,
        agency_fee_percent=payload.agency_fee_percent,
        agency_fee_include_in_estimate=payload.agency_fee_include_in_estimate,
        project_price_total=payload.project_price_total,
        expected_from_client_total=payload.expected_from_client_total,
        closed_at=payload.closed_at,
    )
    db.add(p)
    db.commit()
    db.refresh(p)

    # default groups
    for idx, name in enumerate(["Стройка", "Команда", "Дизайн"]):
        g = ExpenseGroup(project_id=p.id, name=name, sort_order=idx)
        db.add(g)
    db.commit()
    return p

@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    return _get_project_or_404(db, project_id)

@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)):
    p = _get_project_or_404(db, project_id)

    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)

    db.commit()
    db.refresh(p)
    return p

@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = _get_project_or_404(db, project_id)
    db.delete(p)
    db.commit()
    return {"deleted": True}

@router.get("/{project_id}/computed", response_model=ProjectComputed)
def project_computed(project_id: int, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    return compute_project_financials(db, project_id)

@router.get("/{project_id}/groups", response_model=list[GroupOut])
def list_groups(project_id: int, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    return db.execute(select(ExpenseGroup).where(ExpenseGroup.project_id == project_id).order_by(ExpenseGroup.sort_order.asc())).scalars().all()

@router.post("/{project_id}/groups", response_model=GroupOut)
def create_group(project_id: int, payload: GroupCreate, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    g = ExpenseGroup(project_id=project_id, name=payload.name, sort_order=payload.sort_order)
    db.add(g)
    db.commit()
    db.refresh(g)
    return g

@router.patch("/{project_id}/groups/{group_id}", response_model=GroupOut)
def update_group(project_id: int, group_id: int, payload: GroupUpdate, db: Session = Depends(get_db)):
    g = _get_group_or_404(db, project_id, group_id)
    data = payload.model_dump(exclude_unset=True)

    if "name" in data and data["name"] is not None:
        name = str(data["name"]).strip()
        if not name:
            raise HTTPException(422, "GROUP_NAME_EMPTY")
        g.name = name

    if "sort_order" in data and data["sort_order"] is not None:
        g.sort_order = int(data["sort_order"])

    db.commit()
    db.refresh(g)
    return g

@router.delete("/{project_id}/groups/{group_id}")
def delete_group(project_id: int, group_id: int, db: Session = Depends(get_db)):
    g = _get_group_or_404(db, project_id, group_id)
    db.delete(g)
    db.commit()
    return {"deleted": True}

@router.get("/{project_id}/items", response_model=list[ItemOut])
def list_items(project_id: int, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    items = db.execute(
        select(ExpenseItem).where(ExpenseItem.project_id == project_id).order_by(ExpenseItem.group_id.asc(), ExpenseItem.id.asc())
    ).scalars().all()
    return _attach_item_discounts(db, project_id, items)

@router.post("/{project_id}/items", response_model=ItemOut)
def create_item(project_id: int, payload: ItemCreate, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    _get_group_or_404(db, project_id, payload.group_id)
    mode = _parse_mode(payload.mode)
    _validate_parent_item(
        db=db,
        project_id=project_id,
        group_id=payload.group_id,
        parent_item_id=payload.parent_item_id,
    )

    it = ExpenseItem(
        stable_item_id=gen_stable_id("item"),
        project_id=project_id,
        group_id=payload.group_id,
        parent_item_id=payload.parent_item_id,
        title=payload.title,
        mode=mode,
        qty=payload.qty,
        unit_price_base=payload.unit_price_base,
        base_total=payload.base_total,
        include_in_estimate=payload.include_in_estimate if payload.parent_item_id is None else False,
        extra_profit_enabled=payload.extra_profit_enabled,
        extra_profit_amount=payload.extra_profit_amount,
        planned_pay_date=payload.planned_pay_date,
    )
    _refresh_item_calculated_base(it)
    db.add(it)
    db.flush()
    _apply_item_discount(
        db=db,
        item_id=int(it.id),
        discount_enabled=bool(payload.discount_enabled),
        discount_amount=float(payload.discount_amount or 0.0),
    )
    db.commit()
    db.refresh(it)
    _attach_item_discounts(db, project_id, [it])
    return it

@router.patch("/{project_id}/items/{item_id}", response_model=ItemOut)
def update_item(project_id: int, item_id: int, payload: ItemUpdate, db: Session = Depends(get_db)):
    it = _get_item_or_404(db, project_id, item_id)
    data = payload.model_dump(exclude_unset=True)
    discount_enabled = data.pop("discount_enabled", None)
    discount_amount = data.pop("discount_amount", None)
    has_children = db.execute(
        select(ExpenseItem.id).where(ExpenseItem.parent_item_id == item_id).limit(1)
    ).first() is not None

    if "group_id" in data and data["group_id"] is not None:
        _get_group_or_404(db, project_id, data["group_id"])
        if has_children and int(data["group_id"]) != it.group_id:
            raise HTTPException(422, "ITEM_WITH_SUBITEMS_CANNOT_CHANGE_GROUP")

    if "mode" in data and data["mode"] is not None:
        data["mode"] = _parse_mode(data["mode"])

    target_group_id = int(data["group_id"]) if data.get("group_id") is not None else int(it.group_id)
    target_parent_item_id = data["parent_item_id"] if "parent_item_id" in data else it.parent_item_id
    _validate_parent_item(
        db=db,
        project_id=project_id,
        group_id=target_group_id,
        parent_item_id=target_parent_item_id,
        current_item_id=item_id,
    )

    for k, v in data.items():
        setattr(it, k, v)

    if it.parent_item_id is not None:
        it.include_in_estimate = False

    _refresh_item_calculated_base(it)
    if discount_enabled is not None or discount_amount is not None:
        current_adj = _load_discount_adjustment_for_item(db, item_id)
        resolved_enabled = bool(discount_enabled) if discount_enabled is not None else bool(current_adj.discount_enabled) if current_adj else False
        resolved_amount = float(discount_amount) if discount_amount is not None else float(current_adj.discount_amount or 0.0) if current_adj else 0.0
        _apply_item_discount(
            db=db,
            item_id=item_id,
            discount_enabled=resolved_enabled,
            discount_amount=resolved_amount,
        )
    db.commit()
    db.refresh(it)
    _attach_item_discounts(db, project_id, [it])
    return it

@router.delete("/{project_id}/items/{item_id}")
def delete_item(project_id: int, item_id: int, db: Session = Depends(get_db)):
    it = _get_item_or_404(db, project_id, item_id)
    subitems = db.execute(
        select(ExpenseItem).where(ExpenseItem.parent_item_id == item_id)
    ).scalars().all()
    for subitem in subitems:
        db.delete(subitem)
    db.delete(it)
    db.commit()
    return {"deleted": True}

@router.get("/{project_id}/items/{item_id}/adjustment", response_model=BillingAdjustmentOut)
def get_item_adjustment(project_id: int, item_id: int, db: Session = Depends(get_db)):
    _get_item_or_404(db, project_id, item_id)
    adj = db.execute(
        select(ClientBillingAdjustment).where(ClientBillingAdjustment.expense_item_id == item_id)
    ).scalar_one_or_none()
    if not adj:
        raise HTTPException(404, "ADJUSTMENT_NOT_FOUND")
    return adj

@router.put("/{project_id}/items/{item_id}/adjustment", response_model=BillingAdjustmentOut)
def upsert_item_adjustment(project_id: int, item_id: int, payload: BillingAdjustmentUpsert, db: Session = Depends(get_db)):
    _get_item_or_404(db, project_id, item_id)
    adj = db.execute(
        select(ClientBillingAdjustment).where(ClientBillingAdjustment.expense_item_id == item_id)
    ).scalar_one_or_none()
    adj_type = _parse_adjustment_type(payload.adjustment_type)

    if not adj:
        adj = ClientBillingAdjustment(
            expense_item_id=item_id,
            unit_price_full=payload.unit_price_full,
            unit_price_billable=payload.unit_price_billable,
            adjustment_type=adj_type,
            reason=payload.reason,
        )
        db.add(adj)
    else:
        adj.unit_price_full = payload.unit_price_full
        adj.unit_price_billable = payload.unit_price_billable
        adj.adjustment_type = adj_type
        adj.reason = payload.reason

    db.commit()
    db.refresh(adj)
    return adj

@router.delete("/{project_id}/items/{item_id}/adjustment")
def delete_item_adjustment(project_id: int, item_id: int, db: Session = Depends(get_db)):
    _get_item_or_404(db, project_id, item_id)
    adj = db.execute(
        select(ClientBillingAdjustment).where(ClientBillingAdjustment.expense_item_id == item_id)
    ).scalar_one_or_none()
    if not adj:
        raise HTTPException(404, "ADJUSTMENT_NOT_FOUND")
    db.delete(adj)
    db.commit()
    return {"deleted": True}

@router.get("/{project_id}/payments/plan", response_model=list[PaymentPlanOut])
def list_payments_plan(project_id: int, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    today = date.today()
    return db.execute(
        select(ClientPaymentsPlan).where(
            ClientPaymentsPlan.project_id == project_id,
            ClientPaymentsPlan.pay_date > today,
        ).order_by(ClientPaymentsPlan.pay_date.asc(), ClientPaymentsPlan.id.asc())
    ).scalars().all()

@router.post("/{project_id}/payments/plan", response_model=PaymentPlanOut)
def create_payment_plan(project_id: int, payload: PaymentPlanCreate, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    rec = ClientPaymentsPlan(
        stable_pay_id=gen_stable_id("pay"),
        project_id=project_id,
        pay_date=payload.pay_date,
        amount=payload.amount,
        note=payload.note,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec

@router.patch("/{project_id}/payments/plan/{pay_id}", response_model=PaymentPlanOut)
def update_payment_plan(project_id: int, pay_id: int, payload: PaymentPlanUpdate, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    rec = db.get(ClientPaymentsPlan, pay_id)
    if not rec or rec.project_id != project_id:
        raise HTTPException(404, "PAYMENT_PLAN_NOT_FOUND")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(rec, k, v)
    db.commit()
    db.refresh(rec)
    return rec

@router.delete("/{project_id}/payments/plan/{pay_id}")
def delete_payment_plan(project_id: int, pay_id: int, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    rec = db.get(ClientPaymentsPlan, pay_id)
    if not rec or rec.project_id != project_id:
        raise HTTPException(404, "PAYMENT_PLAN_NOT_FOUND")
    db.delete(rec)
    db.commit()
    return {"deleted": True}

@router.get("/{project_id}/payments/fact", response_model=list[PaymentFactOut])
def list_payments_fact(project_id: int, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    today = date.today()
    facts = db.execute(
        select(ClientPaymentsFact).where(ClientPaymentsFact.project_id == project_id).order_by(ClientPaymentsFact.pay_date.asc(), ClientPaymentsFact.id.asc())
    ).scalars().all()
    due_plans = db.execute(
        select(ClientPaymentsPlan).where(
            ClientPaymentsPlan.project_id == project_id,
            ClientPaymentsPlan.pay_date <= today,
        ).order_by(ClientPaymentsPlan.pay_date.asc(), ClientPaymentsPlan.id.asc())
    ).scalars().all()

    rows: list[dict] = [
        {
            "id": int(f.id),
            "project_id": int(f.project_id),
            "pay_date": f.pay_date,
            "amount": float(f.amount),
            "note": f.note,
        }
        for f in facts
    ]
    rows.extend([
        {
            "id": -int(p.id),
            "project_id": int(p.project_id),
            "pay_date": p.pay_date,
            "amount": float(p.amount),
            "note": p.note,
        }
        for p in due_plans
    ])
    rows.sort(key=lambda r: (r["pay_date"], r["id"]))
    return rows

@router.post("/{project_id}/payments/fact", response_model=PaymentFactOut)
def create_payment_fact(project_id: int, payload: PaymentFactCreate, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    rec = ClientPaymentsFact(
        project_id=project_id,
        pay_date=payload.pay_date,
        amount=payload.amount,
        note=payload.note,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec

@router.patch("/{project_id}/payments/fact/{fact_id}", response_model=PaymentFactOut)
def update_payment_fact(project_id: int, fact_id: int, payload: PaymentFactUpdate, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    if fact_id < 0:
        plan_id = -fact_id
        rec_plan = db.get(ClientPaymentsPlan, plan_id)
        if not rec_plan or rec_plan.project_id != project_id:
            raise HTTPException(404, "PAYMENT_FACT_NOT_FOUND")
        for k, v in payload.model_dump(exclude_unset=True).items():
            setattr(rec_plan, k, v)
        db.commit()
        db.refresh(rec_plan)
        return {
            "id": -int(rec_plan.id),
            "project_id": int(rec_plan.project_id),
            "pay_date": rec_plan.pay_date,
            "amount": float(rec_plan.amount),
            "note": rec_plan.note,
        }

    rec = db.get(ClientPaymentsFact, fact_id)
    if not rec or rec.project_id != project_id:
        raise HTTPException(404, "PAYMENT_FACT_NOT_FOUND")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(rec, k, v)
    db.commit()
    db.refresh(rec)
    return rec

@router.delete("/{project_id}/payments/fact/{fact_id}")
def delete_payment_fact(project_id: int, fact_id: int, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    if fact_id < 0:
        plan_id = -fact_id
        rec_plan = db.get(ClientPaymentsPlan, plan_id)
        if not rec_plan or rec_plan.project_id != project_id:
            raise HTTPException(404, "PAYMENT_FACT_NOT_FOUND")
        db.delete(rec_plan)
        db.commit()
        return {"deleted": True}

    rec = db.get(ClientPaymentsFact, fact_id)
    if not rec or rec.project_id != project_id:
        raise HTTPException(404, "PAYMENT_FACT_NOT_FOUND")
    db.delete(rec)
    db.commit()
    return {"deleted": True}
