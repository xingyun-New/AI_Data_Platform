"""Desensitization rules CRUD."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.deps_rbac import require_sys_admin
from app.database import get_db
from app.models.rule import DesensitizeRule

router = APIRouter()


class RuleCreate(BaseModel):
    department: str
    rule_name: str
    rule_description: str
    rule_type: str = "replace"
    priority: int = 0
    is_active: bool = True


class RuleUpdate(BaseModel):
    department: str | None = None
    rule_name: str | None = None
    rule_description: str | None = None
    rule_type: str | None = None
    priority: int | None = None
    is_active: bool | None = None


class RuleOut(BaseModel):
    id: int
    department: str
    rule_name: str
    rule_description: str
    rule_type: str
    priority: int
    is_active: bool
    created_by: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.get("")
def list_rules(
    department: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    q = db.query(DesensitizeRule)
    if department:
        # Support partial match: CH70 matches CH70, CH70/CH73, ALL/CH70, etc.
        q = q.filter(
            (DesensitizeRule.department == department) |
            (DesensitizeRule.department.contains(department))
        )
    total = q.count()
    rows = q.order_by(DesensitizeRule.priority.desc()).offset((page - 1) * size).limit(size).all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            RuleOut(
                id=r.id,
                department=r.department,
                rule_name=r.rule_name,
                rule_description=r.rule_description,
                rule_type=r.rule_type,
                priority=r.priority,
                is_active=r.is_active,
                created_by=r.created_by,
                created_at=str(r.created_at or ""),
                updated_at=str(r.updated_at or ""),
            )
            for r in rows
        ]
    }


@router.post("", response_model=RuleOut)
def create_rule(
    body: RuleCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_sys_admin),
):
    rule = DesensitizeRule(
        department=body.department,
        rule_name=body.rule_name,
        rule_description=body.rule_description,
        rule_type=body.rule_type,
        priority=body.priority,
        is_active=body.is_active,
        created_by=user["username"],
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return RuleOut(
        id=rule.id,
        department=rule.department,
        rule_name=rule.rule_name,
        rule_description=rule.rule_description,
        rule_type=rule.rule_type,
        priority=rule.priority,
        is_active=rule.is_active,
        created_by=rule.created_by,
        created_at=str(rule.created_at or ""),
        updated_at=str(rule.updated_at or ""),
    )


@router.put("/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: int,
    body: RuleUpdate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_sys_admin),
):
    rule = db.get(DesensitizeRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return RuleOut(
        id=rule.id,
        department=rule.department,
        rule_name=rule.rule_name,
        rule_description=rule.rule_description,
        rule_type=rule.rule_type,
        priority=rule.priority,
        is_active=rule.is_active,
        created_by=rule.created_by,
        created_at=str(rule.created_at or ""),
        updated_at=str(rule.updated_at or ""),
    )


@router.delete("/{rule_id}")
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_sys_admin),
):
    rule = db.get(DesensitizeRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    db.delete(rule)
    db.commit()
    return {"status": "deleted", "id": rule_id}
