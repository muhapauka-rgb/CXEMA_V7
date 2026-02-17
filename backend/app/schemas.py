from __future__ import annotations

from datetime import datetime, date
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field

class ProjectCreate(BaseModel):
    title: str
    client_name: Optional[str] = None
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    google_drive_url: Optional[str] = None
    google_drive_folder: Optional[str] = None
    agency_fee_percent: float = Field(default=10.0, ge=0)
    agency_fee_include_in_estimate: bool = True
    project_price_total: float = 0.0
    expected_from_client_total: float = 0.0
    closed_at: Optional[date] = None

class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    client_name: Optional[str] = None
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    google_drive_url: Optional[str] = None
    google_drive_folder: Optional[str] = None
    agency_fee_percent: Optional[float] = Field(default=None, ge=0)
    agency_fee_include_in_estimate: Optional[bool] = None
    project_price_total: Optional[float] = None
    expected_from_client_total: Optional[float] = None
    closed_at: Optional[date] = None

class ProjectOut(BaseModel):
    id: int
    title: str
    client_name: Optional[str]
    client_email: Optional[str]
    client_phone: Optional[str]
    google_drive_url: Optional[str]
    google_drive_folder: Optional[str]
    project_price_total: float
    expected_from_client_total: float
    agency_fee_percent: float
    agency_fee_include_in_estimate: bool
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[date]

    class Config:
        from_attributes = True

class GroupCreate(BaseModel):
    name: str
    sort_order: int = 0

class GroupUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None

class GroupOut(BaseModel):
    id: int
    project_id: int
    name: str
    sort_order: int
    class Config:
        from_attributes = True

class ItemCreate(BaseModel):
    group_id: int
    title: str
    mode: str = "SINGLE_TOTAL"
    qty: Optional[float] = Field(default=None, ge=0)
    unit_price_base: Optional[float] = Field(default=None, ge=0)
    base_total: float = Field(default=0.0, ge=0)
    include_in_estimate: bool = True
    extra_profit_enabled: bool = False
    extra_profit_amount: float = Field(default=0.0, ge=0)
    planned_pay_date: Optional[date] = None

class ItemUpdate(BaseModel):
    group_id: Optional[int] = None
    title: Optional[str] = None
    mode: Optional[str] = None
    qty: Optional[float] = Field(default=None, ge=0)
    unit_price_base: Optional[float] = Field(default=None, ge=0)
    base_total: Optional[float] = Field(default=None, ge=0)
    include_in_estimate: Optional[bool] = None
    extra_profit_enabled: Optional[bool] = None
    extra_profit_amount: Optional[float] = Field(default=None, ge=0)
    planned_pay_date: Optional[date] = None

class ItemOut(BaseModel):
    id: int
    stable_item_id: str
    project_id: int
    group_id: int
    title: str
    mode: str
    qty: Optional[float]
    unit_price_base: Optional[float]
    base_total: float
    include_in_estimate: bool
    extra_profit_enabled: bool
    extra_profit_amount: float
    planned_pay_date: Optional[date]

    class Config:
        from_attributes = True

class BillingAdjustmentUpsert(BaseModel):
    unit_price_full: float = Field(default=0.0, ge=0)
    unit_price_billable: float = Field(default=0.0, ge=0)
    adjustment_type: str = "DISCOUNT"
    reason: str = ""

class BillingAdjustmentOut(BaseModel):
    expense_item_id: int
    unit_price_full: float
    unit_price_billable: float
    adjustment_type: str
    reason: str

    class Config:
        from_attributes = True

class PaymentPlanCreate(BaseModel):
    pay_date: date
    amount: float = Field(default=0.0, ge=0)
    note: str = ""

class PaymentPlanUpdate(BaseModel):
    pay_date: Optional[date] = None
    amount: Optional[float] = Field(default=None, ge=0)
    note: Optional[str] = None

class PaymentPlanOut(BaseModel):
    id: int
    stable_pay_id: str
    project_id: int
    pay_date: date
    amount: float
    note: str

    class Config:
        from_attributes = True

class PaymentFactCreate(BaseModel):
    pay_date: date
    amount: float = Field(default=0.0, ge=0)
    note: str = ""

class PaymentFactUpdate(BaseModel):
    pay_date: Optional[date] = None
    amount: Optional[float] = Field(default=None, ge=0)
    note: Optional[str] = None

class PaymentFactOut(BaseModel):
    id: int
    project_id: int
    pay_date: date
    amount: float
    note: str

    class Config:
        from_attributes = True

class SheetsStatusOut(BaseModel):
    mode: str
    spreadsheet_id: Optional[str] = None
    sheet_tab_name: Optional[str] = None
    sheet_url: Optional[str] = None
    mock_file_path: Optional[str] = None
    last_published_at: Optional[datetime] = None
    last_imported_at: Optional[datetime] = None

class SheetsPublishOut(BaseModel):
    status: str
    spreadsheet_id: str
    sheet_url: Optional[str] = None
    mock_file_path: Optional[str] = None
    last_published_at: datetime
    estimate_rows: int
    payments_plan_rows: int

class SheetsItemDiffOut(BaseModel):
    item_id: str
    title: str
    changes: Dict[str, Dict[str, Any]]

class SheetsPaymentDiffOut(BaseModel):
    pay_id: str
    changes: Dict[str, Dict[str, Any]]

class SheetsPaymentNewOut(BaseModel):
    pay_date: str
    amount: float
    note: str

class SheetsImportPreviewOut(BaseModel):
    preview_token: str
    items_updated: List[SheetsItemDiffOut]
    payments_updated: List[SheetsPaymentDiffOut]
    payments_new: List[SheetsPaymentNewOut]
    errors: List[str]

class SheetsImportApplyIn(BaseModel):
    preview_token: str

class SheetsImportApplyOut(BaseModel):
    applied_items: int
    applied_payments_updated: int
    applied_payments_new: int
    errors: List[str]
    imported_at: Optional[datetime] = None

class GoogleAuthStatusOut(BaseModel):
    mode: str
    connected: bool
    client_secret_configured: bool
    redirect_uri: str
    token_file_path: str
    last_error: Optional[str] = None

class GoogleAuthStartOut(BaseModel):
    auth_url: str
    state: str

class GoogleAuthCallbackOut(BaseModel):
    connected: bool
    message: str

class ProjectComputed(BaseModel):
    project_id: int
    expenses_total: float
    agency_fee: float
    extra_profit_total: float
    in_pocket: float
    diff: float

class SnapshotTotals(BaseModel):
    active_projects_count: int
    received_total: float
    spent_total: float
    balance_total: float
    planned_total: float
    expected_total: float
    agency_fee_to_date: float
    extra_profit_to_date: float
    in_pocket_to_date: float

class SnapshotProject(BaseModel):
    project_id: int
    title: str
    active: bool
    received_to_date: float
    spent_to_date: float
    balance_to_date: float
    expected_total: float
    remaining: float
    agency_fee_to_date: float
    extra_profit_to_date: float
    in_pocket_to_date: float

class OverviewSnapshot(BaseModel):
    meta: dict
    totals: SnapshotTotals
    projects: List[SnapshotProject]

class OverviewMonthRange(BaseModel):
    min_month: str
    max_month: str

class LifePeriod(BaseModel):
    month_start: date
    month_end: date
    label: str

class LifeProjectBreakdown(BaseModel):
    project_id: int
    title: str
    organization: Optional[str] = None
    received_last_month: float
    to_life: float
    to_savings: float

class LifePreviousMonthOut(BaseModel):
    period: LifePeriod
    target_amount: float
    life_covered: float
    life_gap: float
    savings_total: float
    projects: List[LifeProjectBreakdown]
