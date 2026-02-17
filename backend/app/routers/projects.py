from __future__ import annotations

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
    return db.execute(
        select(ExpenseItem).where(ExpenseItem.project_id == project_id).order_by(ExpenseItem.group_id.asc(), ExpenseItem.id.asc())
    ).scalars().all()

@router.post("/{project_id}/items", response_model=ItemOut)
def create_item(project_id: int, payload: ItemCreate, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    _get_group_or_404(db, project_id, payload.group_id)
    mode = _parse_mode(payload.mode)

    it = ExpenseItem(
        stable_item_id=gen_stable_id("item"),
        project_id=project_id,
        group_id=payload.group_id,
        title=payload.title,
        mode=mode,
        qty=payload.qty,
        unit_price_base=payload.unit_price_base,
        base_total=payload.base_total,
        include_in_estimate=payload.include_in_estimate,
        extra_profit_enabled=payload.extra_profit_enabled,
        extra_profit_amount=payload.extra_profit_amount,
        planned_pay_date=payload.planned_pay_date,
    )
    _refresh_item_calculated_base(it)
    db.add(it)
    db.commit()
    db.refresh(it)
    return it

@router.patch("/{project_id}/items/{item_id}", response_model=ItemOut)
def update_item(project_id: int, item_id: int, payload: ItemUpdate, db: Session = Depends(get_db)):
    it = _get_item_or_404(db, project_id, item_id)
    data = payload.model_dump(exclude_unset=True)

    if "group_id" in data and data["group_id"] is not None:
        _get_group_or_404(db, project_id, data["group_id"])

    if "mode" in data and data["mode"] is not None:
        data["mode"] = _parse_mode(data["mode"])

    for k, v in data.items():
        setattr(it, k, v)

    _refresh_item_calculated_base(it)
    db.commit()
    db.refresh(it)
    return it

@router.delete("/{project_id}/items/{item_id}")
def delete_item(project_id: int, item_id: int, db: Session = Depends(get_db)):
    it = _get_item_or_404(db, project_id, item_id)
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
    return db.execute(
        select(ClientPaymentsPlan).where(ClientPaymentsPlan.project_id == project_id).order_by(ClientPaymentsPlan.pay_date.asc(), ClientPaymentsPlan.id.asc())
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
    return db.execute(
        select(ClientPaymentsFact).where(ClientPaymentsFact.project_id == project_id).order_by(ClientPaymentsFact.pay_date.asc(), ClientPaymentsFact.id.asc())
    ).scalars().all()

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
    rec = db.get(ClientPaymentsFact, fact_id)
    if not rec or rec.project_id != project_id:
        raise HTTPException(404, "PAYMENT_FACT_NOT_FOUND")
    db.delete(rec)
    db.commit()
    return {"deleted": True}
