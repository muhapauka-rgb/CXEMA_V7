from __future__ import annotations

import enum
from datetime import datetime, date
from typing import Optional, Dict, Any

from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, Date, ForeignKey, Enum, Text, JSON, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class ItemMode(str, enum.Enum):
    SINGLE_TOTAL = "SINGLE_TOTAL"
    QTY_PRICE = "QTY_PRICE"


class AdjustmentType(str, enum.Enum):
    DISCOUNT = "DISCOUNT"
    CREDIT_FROM_PREV = "CREDIT_FROM_PREV"
    CARRY_TO_NEXT = "CARRY_TO_NEXT"


class ImportStatus(str, enum.Enum):
    uploaded = "uploaded"
    parsed = "parsed"
    mapped = "mapped"
    applied = "applied"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    project_price_total: Mapped[float] = mapped_column(Float, default=0.0)  # Стоимость проекта
    expected_from_client_total: Mapped[float] = mapped_column(Float, default=0.0)  # Ждём всего
    agency_fee_percent: Mapped[float] = mapped_column(Float, default=10.0)
    agency_fee_include_in_estimate: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    groups = relationship("ExpenseGroup", back_populates="project", cascade="all, delete-orphan")
    payments_plan = relationship("ClientPaymentsPlan", back_populates="project", cascade="all, delete-orphan")
    payments_fact = relationship("ClientPaymentsFact", back_populates="project", cascade="all, delete-orphan")
    sheet_link = relationship("GoogleSheetLink", back_populates="project", uselist=False, cascade="all, delete-orphan")


class ExpenseGroup(Base):
    __tablename__ = "expense_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    project = relationship("Project", back_populates="groups")
    items = relationship("ExpenseItem", back_populates="group", cascade="all, delete-orphan")


class ExpenseItem(Base):
    __tablename__ = "expense_items"
    __table_args__ = (
        UniqueConstraint("project_id", "stable_item_id", name="uq_item_stable_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stable_item_id: Mapped[str] = mapped_column(String(64), index=True)  # стабильный ID для Sheets
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("expense_groups.id", ondelete="CASCADE"), index=True)

    title: Mapped[str] = mapped_column(String(255))
    mode: Mapped[ItemMode] = mapped_column(Enum(ItemMode), default=ItemMode.SINGLE_TOTAL)

    qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit_price_base: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    base_total: Mapped[float] = mapped_column(Float, default=0.0)

    extra_profit_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    extra_profit_amount: Mapped[float] = mapped_column(Float, default=0.0)
    include_in_estimate: Mapped[bool] = mapped_column(Boolean, default=True)

    planned_pay_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    group = relationship("ExpenseGroup", back_populates="items")
    adjustment = relationship(
        "ClientBillingAdjustment",
        back_populates="item",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ClientBillingAdjustment(Base):
    __tablename__ = "client_billing_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    expense_item_id: Mapped[int] = mapped_column(
        ForeignKey("expense_items.id", ondelete="CASCADE"),
        unique=True,
    )

    unit_price_full: Mapped[float] = mapped_column(Float, default=0.0)
    unit_price_billable: Mapped[float] = mapped_column(Float, default=0.0)
    adjustment_type: Mapped[AdjustmentType] = mapped_column(Enum(AdjustmentType), default=AdjustmentType.DISCOUNT)
    reason: Mapped[str] = mapped_column(String(512), default="")

    item = relationship("ExpenseItem", back_populates="adjustment")


class ClientPaymentsPlan(Base):
    __tablename__ = "client_payments_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stable_pay_id: Mapped[str] = mapped_column(String(64), index=True)  # для Sheets
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)

    pay_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(String(512), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="payments_plan")


class ClientPaymentsFact(Base):
    __tablename__ = "client_payments_fact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)

    pay_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(String(512), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="payments_fact")


class GoogleSheetLink(Base):
    __tablename__ = "google_sheet_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True)

    spreadsheet_id: Mapped[str] = mapped_column(String(128))
    sheet_tab_name: Mapped[str] = mapped_column(String(64), default="PROJECT")
    last_published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_imported_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    project = relationship("Project", back_populates="sheet_link")


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("expense_groups.id", ondelete="CASCADE"), index=True)

    file_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(32))
    raw_file_path: Mapped[str] = mapped_column(String(512))

    status: Mapped[ImportStatus] = mapped_column(Enum(ImportStatus), default=ImportStatus.uploaded)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    raw_rows = relationship("ImportRowRaw", back_populates="job", cascade="all, delete-orphan")
    candidates = relationship("ImportItemCandidate", back_populates="job", cascade="all, delete-orphan")


class ImportRowRaw(Base):
    __tablename__ = "import_rows_raw"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    import_job_id: Mapped[int] = mapped_column(ForeignKey("import_jobs.id", ondelete="CASCADE"), index=True)
    row_index: Mapped[int] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    raw_cells: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    job = relationship("ImportJob", back_populates="raw_rows")


class ImportItemCandidate(Base):
    __tablename__ = "import_item_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    import_job_id: Mapped[int] = mapped_column(ForeignKey("import_jobs.id", ondelete="CASCADE"), index=True)

    title: Mapped[str] = mapped_column(String(255), default="")
    qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    selected: Mapped[bool] = mapped_column(Boolean, default=True)

    job = relationship("ImportJob", back_populates="candidates")
