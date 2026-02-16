from __future__ import annotations

from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, Field

class ProjectCreate(BaseModel):
    title: str
    client_name: Optional[str] = None
    project_price_total: float = 0.0
    expected_from_client_total: float = 0.0
    closed_at: Optional[date] = None

class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    client_name: Optional[str] = None
    project_price_total: Optional[float] = None
    expected_from_client_total: Optional[float] = None
    closed_at: Optional[date] = None

class ProjectOut(BaseModel):
    id: int
    title: str
    client_name: Optional[str]
    project_price_total: float
    expected_from_client_total: float
    agency_fee_percent: float
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[date]

    class Config:
        from_attributes = True

class GroupCreate(BaseModel):
    name: str
    sort_order: int = 0

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
    qty: Optional[float] = None
    unit_price_base: Optional[float] = None
    base_total: float = 0.0
    extra_profit_enabled: bool = False
    extra_profit_amount: float = 0.0

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
    extra_profit_enabled: bool
    extra_profit_amount: float

    class Config:
        from_attributes = True

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
    expected_total: float
    remaining: float
    agency_fee_to_date: float
    extra_profit_to_date: float
    in_pocket_to_date: float

class OverviewSnapshot(BaseModel):
    meta: dict
    totals: SnapshotTotals
    projects: List[SnapshotProject]
