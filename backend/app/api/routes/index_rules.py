"""Index rules CRUD — department-level rules for index generation & shared_departments."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models.index_rule import IndexRule

router = APIRouter()


class IndexRuleCreate(BaseModel):
    department: str
    rule_name: str
    rule_description: str
    rule_type: str = "share"
    target_departments: list[str] = []
    priority: int = 0
    is_active: bool = True


class IndexRuleUpdate(BaseModel):
    department: str | None = None
    rule_name: str | None = None
    rule_description: str | None = None
    rule_type: str | None = None
    target_departments: list[str] | None = None
    priority: int | None = None
    is_active: bool | None = None


class IndexRuleOut(BaseModel):
    id: int
    department: str
    rule_name: str
    rule_description: str
    rule_type: str
    target_departments: list[str]
    priority: int
    is_active: bool
    created_by: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


def _parse_target_depts(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _to_out(r: IndexRule) -> IndexRuleOut:
    return IndexRuleOut(
        id=r.id,
        department=r.department,
        rule_name=r.rule_name,
        rule_description=r.rule_description,
        rule_type=r.rule_type,
        target_departments=_parse_target_depts(r.target_departments),
        priority=r.priority,
        is_active=r.is_active,
        created_by=r.created_by,
        created_at=str(r.created_at or ""),
        updated_at=str(r.updated_at or ""),
    )


@router.get("")
def list_index_rules(
    department: str | None = Query(None),
    rule_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    q = db.query(IndexRule)
    if department:
        # Support partial match: CH70 matches CH70, CH70/CH73, ALL/CH70, etc.
        q = q.filter(
            (IndexRule.department == department) |
            (IndexRule.department.contains(department))
        )
    if rule_type:
        q = q.filter(IndexRule.rule_type == rule_type)
    total = q.count()
    rows = q.order_by(IndexRule.priority.desc()).offset((page - 1) * size).limit(size).all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [_to_out(r) for r in rows]
    }


@router.post("", response_model=IndexRuleOut)
def create_index_rule(
    body: IndexRuleCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    rule = IndexRule(
        department=body.department,
        rule_name=body.rule_name,
        rule_description=body.rule_description,
        rule_type=body.rule_type,
        target_departments=json.dumps(body.target_departments, ensure_ascii=False),
        priority=body.priority,
        is_active=body.is_active,
        created_by=user["username"],
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.put("/{rule_id}", response_model=IndexRuleOut)
def update_index_rule(
    rule_id: int,
    body: IndexRuleUpdate,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    rule = db.get(IndexRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="索引规则不存在")
    data = body.model_dump(exclude_unset=True)
    if "target_departments" in data:
        data["target_departments"] = json.dumps(data["target_departments"], ensure_ascii=False)
    for field, value in data.items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.delete("/{rule_id}")
def delete_index_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    rule = db.get(IndexRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="索引规则不存在")
    db.delete(rule)
    db.commit()
    return {"status": "deleted", "id": rule_id}
