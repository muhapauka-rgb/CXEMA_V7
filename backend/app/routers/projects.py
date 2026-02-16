from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..db import get_db, engine, Base
from ..models import Project, ExpenseGroup
from ..schemas import ProjectCreate, ProjectUpdate, ProjectOut, GroupCreate, GroupOut, ProjectComputed
from ..utils import compute_project_financials

router = APIRouter(prefix="/api/projects", tags=["projects"])

# MVP: create tables automatically on first import (без alembic пока)
Base.metadata.create_all(bind=engine)

@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.execute(select(Project).order_by(Project.id.desc())).scalars().all()

@router.post("", response_model=ProjectOut)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    p = Project(
        title=payload.title,
        client_name=payload.client_name,
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
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "PROJECT_NOT_FOUND")
    return p

@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "PROJECT_NOT_FOUND")

    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)

    db.commit()
    db.refresh(p)
    return p

@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "PROJECT_NOT_FOUND")
    db.delete(p)
    db.commit()
    return {"deleted": True}

@router.get("/{project_id}/computed", response_model=ProjectComputed)
def project_computed(project_id: int, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "PROJECT_NOT_FOUND")
    return compute_project_financials(db, project_id)

@router.get("/{project_id}/groups", response_model=list[GroupOut])
def list_groups(project_id: int, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "PROJECT_NOT_FOUND")
    return db.execute(select(ExpenseGroup).where(ExpenseGroup.project_id == project_id).order_by(ExpenseGroup.sort_order.asc())).scalars().all()

@router.post("/{project_id}/groups", response_model=GroupOut)
def create_group(project_id: int, payload: GroupCreate, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "PROJECT_NOT_FOUND")
    g = ExpenseGroup(project_id=project_id, name=payload.name, sort_order=payload.sort_order)
    db.add(g)
    db.commit()
    db.refresh(g)
    return g
